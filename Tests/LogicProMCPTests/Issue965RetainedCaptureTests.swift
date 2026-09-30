import Foundation
import MCP
import Testing
@testable import LogicProMCP

@Suite("Retained session captures", .serialized)
struct Issue965RetainedCaptureTests {
    private func cache(named name: String = "Kick", clock: CaptureTestClock? = nil) async -> StateCache {
        let cache = StateCache(sessionCaptureNow: { clock?.now() ?? .now })
        await cache.updateProject(ProjectInfo(name: "Fixture", filePath: "/tmp/Fixture.logicx"))
        await cache.updateTracks([TrackState(id: 0, name: name, type: .audio)])
        return cache
    }

    private func inspect(_ cache: StateCache, params: [String: Value] = [:]) async -> CallTool.Result {
        await ProjectDispatcher.handle(
            command: "inspect_session", params: params, router: ChannelRouter(),
            cache: cache, cleanupAuditFileReader: .unavailable
        )
    }

    private func id(_ result: CallTool.Result) throws -> String {
        let body = try #require(sharedJSONObject(sharedToolText(result)))
        return try #require(body["snapshot_id"] as? String)
    }

    @Test func equalRevisionCountersDoNotAliasDifferentCapturesOrSessions() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let firstCache = await cache()
            let otherCache = await cache(named: "Bass")
            let first = try id(await inspect(firstCache))
            let repeated = try id(await inspect(firstCache))
            let other = try id(await inspect(otherCache))
            #expect(first != repeated)
            #expect(first != other)
        }
    }

    @Test func snapshotLookupReturnsTheOriginalBytesInsteadOfRegenerating() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let cache = await cache()
            let original = await inspect(cache)
            let snapshot = try id(original)
            await cache.updateTracks([TrackState(id: 0, name: "Changed by user", type: .audio)])
            let retrieved = await inspect(cache, params: ["snapshot_id": .string(snapshot)])
            let isError = try #require(retrieved.isError)
            #expect(!isError)
            #expect(sharedToolText(retrieved) == sharedToolText(original))
        }
    }

    @Test func anotherCacheCannotRegenerateACrossSessionHandle() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let firstCache = await cache()
            let otherCache = await cache(named: "Other session")
            let snapshot = try id(await inspect(firstCache))
            let result = await inspect(otherCache, params: ["snapshot_id": .string(snapshot)])
            #expect(try #require(result.isError))
            let body = try #require(sharedJSONObject(sharedToolText(result)))
            #expect(body["error"] as? String == "stale_snapshot")
            let attempted = try #require(body["write_attempted"] as? Bool)
            #expect(!attempted)
            #expect(!body.keys.contains("tracks"))
        }
    }
    @Test func lookupDoesNotExtendTheOriginalLifetime() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let clock = CaptureTestClock()
            let cache = await cache(clock: clock)
            let original = await inspect(cache)
            let snapshot = try id(original)
            clock.advance(.seconds(59))
            let beforeExpiry = await inspect(cache, params: ["snapshot_id": .string(snapshot)])
            #expect(sharedToolText(beforeExpiry) == sharedToolText(original))
            clock.advance(.seconds(1))
            let expired = await inspect(cache, params: ["snapshot_id": .string(snapshot)])
            try stale(expired)
        }
    }

    @Test func ninthCaptureEvictsTheOldestButNotTheNext() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let cache = await cache(clock: CaptureTestClock())
            let first = try id(await inspect(cache))
            let second = await inspect(cache)
            let secondID = try id(second)
            for _ in 0..<7 { _ = await inspect(cache) }
            try stale(await inspect(cache, params: ["snapshot_id": .string(first)]))
            let surviving = await inspect(cache, params: ["snapshot_id": .string(secondID)])
            #expect(sharedToolText(surviving) == sharedToolText(second))
        }
    }

    @Test func projectSwitchAndDocumentClosureInvalidateHandles() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let cache = await cache()
            let originalID = try id(await inspect(cache))
            await cache.updateProject(ProjectInfo(name: "Other", filePath: "/tmp/Other.logicx"))
            try stale(await inspect(cache, params: ["snapshot_id": .string(originalID)]))
            let otherID = try id(await inspect(cache))
            await cache.updateDocumentState(false)
            try stale(await inspect(cache, params: ["snapshot_id": .string(otherID)]))
        }
    }

    @Test func lookupCannotReinterpretTheCapturedScopeOrAcceptInvalidIDs() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let cache = await cache()
            let snapshot = try id(await inspect(cache))
            let cases: [[String: Value]] = [
                ["snapshot_id": .int(42)], ["snapshot_id": .string("")],
                ["snapshot_id": .string(snapshot), "scope": .string("selection")],
                ["snapshot_id": .string(snapshot), "domains": .array([.string("color")])],
                ["snapshot_id": .string(snapshot), "allow_ui_navigation": .bool(false)]
            ]
            for params in cases {
                let result = await inspect(cache, params: params)
                let isError = try #require(result.isError)
                #expect(isError)
                let body = try #require(sharedJSONObject(sharedToolText(result)))
                #expect(body["error"] as? String == "invalid_params")
                let attempted = try #require(body["write_attempted"] as? Bool)
                #expect(!attempted)
                #expect(!body.keys.contains("tracks"))
            }
        }
    }

    @Test func oversizedReportIsRefusedWithoutEvictingAnExistingCapture() async throws {
        try await FeatureFlags.withAdr002TargetRefForTests(false) {
            let cache = await cache()
            let original = await inspect(cache)
            let snapshot = try id(original)
            await cache.updateTracks([TrackState(id: 0,
                name: String(repeating: "a", count: 2 * 1024 * 1024), type: .audio)])
            try stale(await inspect(cache))
            let surviving = await inspect(cache, params: ["snapshot_id": .string(snapshot)])
            #expect(sharedToolText(surviving) == sharedToolText(original))
        }
    }

    private func stale(_ result: CallTool.Result) throws {
        let isError = try #require(result.isError)
        #expect(isError)
        let body = try #require(sharedJSONObject(sharedToolText(result)))
        #expect(body["error"] as? String == "stale_snapshot")
        let attempted = try #require(body["write_attempted"] as? Bool)
        #expect(!attempted)
        #expect(!body.keys.contains("tracks"))
    }

}


/// Controlled monotonic time; the dispatcher still runs the real cache and producer.
private final class CaptureTestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var instant = ContinuousClock.now
    func now() -> ContinuousClock.Instant { lock.withLock { instant } }
    func advance(_ duration: Duration) {
        lock.withLock { instant = instant.advanced(by: duration) }
    }
}
