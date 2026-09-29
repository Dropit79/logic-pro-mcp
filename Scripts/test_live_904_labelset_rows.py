#!/usr/bin/env python3
"""Prove the #904 live runner's row classifier never counts a fallback as the set.

`live_904_labelsets_in_every_locale.classify` turns one MCP reply into how a LabelSet was reached:
the set, a named fallback, or not at all. The cases below give it reply shapes the server emits
(the keys are the ones the Swift sources write: `reconciled_modal_kind`,
`track_type_verification_source`, `observed_mode`, `automationMode`, `type`,
`plugin_view_restore_attempted`, `plugin_view_switch_phase`, `regions[].kind`) and assert the
outcome, then drive `run_locale` against a canned driver to show every set gets a row and that the
row count check refuses a locale that is short.

WHAT IS NOT JUDGED
------------------
Nothing here talks to Logic. Whether Logic emits these shapes in each language is what the live
runner measures; this file only proves the classifier reads them honestly.

    python3 test_live_904_labelset_rows.py
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVEKIT = os.path.join(HERE, "livekit")
sys.path.insert(0, LIVEKIT)  # the runner imports `evidence` and live_993 beside it


def load(name):
    """The harness loaded from its file, as livekit/test_quit_refuses_other_documents.py does.

    A `live_*.py` is an entry point, which check-dead-harness-helpers.py relies on; it is loaded
    here by path rather than imported by name so that premise stays true.
    """
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIVEKIT, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load("live_904_labelsets_in_every_locale")

failed = 0


def check(label, ok, detail=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    failed += 0 if ok else 1


def expect(label, got, want):
    check(label, got == want, f"got {got!r}, want {want!r}")


C = R.classify

# deleteTracksPrimaryButton: the English prefix fallback sits beside the set.
expect("an English delete_confirm is the set or the Delete prefix, never the set alone",
       C("deleteTracksPrimaryButton", "en", "delete", {"reconciled_modal_kind": "delete_confirm"}),
       "set_or_fallback:Delete_prefix")
for lproj in ("de", "ja", "zh_TW"):
    expect(f"a {lproj} delete_confirm is the set",
           C("deleteTracksPrimaryButton", lproj, "delete", {"reconciled_modal_kind": "delete_confirm"}),
           "set")
expect("an unknown_sheet on delete is the set refusing",
       C("deleteTracksPrimaryButton", "fr", "delete", {"reconciled_modal_kind": "unknown_sheet"}),
       "refused")
expect("a delete with no sheet did not reach the set",
       C("deleteTracksPrimaryButton", "fr", "delete", {"state": "A"}), "not_reached")

# inspectorChannelStripHelpPrefix / midiEffectSlotHelpKeyword.
family = {"track_type_verification_source": "inspector_channel_strip_instrument_family"}
strip = {"track_type_verification_source": "inspector_channel_strip"}
header = {"track_type_verification_source": "observed_header"}
expect("instrument_family proves the prefix",
       C("inspectorChannelStripHelpPrefix", "ko", "create_instrument", family), "set")
expect("instrument_family proves the MIDI-effect keyword",
       C("midiEffectSlotHelpKeyword", "ko", "create_instrument", family), "set")
expect("inspector_channel_strip proves the prefix",
       C("inspectorChannelStripHelpPrefix", "es", "create_audio", strip), "set")
check("inspector_channel_strip does not prove the MIDI-effect keyword",
      C("midiEffectSlotHelpKeyword", "es", "create_instrument", strip) != "set")
for name in ("inspectorChannelStripHelpPrefix", "midiEffectSlotHelpKeyword"):
    expect(f"observed_header is the fallback for {name}",
           C(name, "it", "create_instrument", header), "fallback:observed_header")
expect("a create with no source did not reach the strip",
       C("inspectorChannelStripHelpPrefix", "it", "create_audio", {"state": "C", "error": "x"}),
       "not_reached")

# trackTypeExternalMIDI.
ext_call = "logic://tracks after create_external_midi"
check("an `unknown` type is not the set",
      C("trackTypeExternalMIDI", "pt", ext_call, {"name": "Ext", "type": "unknown"}) != "set")
expect("an external_midi type is the set or the GM Device set",
       C("trackTypeExternalMIDI", "pt", ext_call, {"name": "MIDI 3", "type": "external_midi"}),
       "set_or_fallback:trackTypeGMDevice")
expect("a GM Device name answers before the set",
       C("trackTypeExternalMIDI", "pt", ext_call, {"name": "GM Device 2", "type": "external_midi"}),
       "fallback:gm_device_name")
expect("a different type is the set refusing",
       C("trackTypeExternalMIDI", "pt", ext_call, {"name": "x", "type": "software_instrument"}),
       "refused")

# automationModeRead / Touch / Write.
expect("`off` read back for a requested read is the unreadable default",
       C("automationModeRead", "de", "logic://tracks after set_automation:read",
         {"automationMode": "off"}),
       "fallback:unreadable_defaults_off")
expect("the requested mode read back is the set",
       C("automationModeWrite", "de", "logic://tracks after set_automation:write",
         {"automationMode": "write"}), "set")
expect("the reply's readable observed_mode is the set",
       C("automationModeTouch", "de", "set_automation:touch", {"observed_mode": "touch"}), "set")
check("a mode read for another request is not the set",
      C("automationModeTouch", "de", "set_automation:touch", {"observed_mode": "read"}) != "set")
check("a Read row cannot be satisfied by a Write call",
      C("automationModeRead", "de", "set_automation:write", {"observed_mode": "read"}) != "set")

# pluginWindowControlsViewMenuItem.
expect("plugin_view_not_confirmed with item_not_found is the set refusing",
       C("pluginWindowControlsViewMenuItem", "zh_CN", "set_param_verified",
         {"error": "plugin_view_not_confirmed", "plugin_view_switch_phase": "item_not_found"}),
       "refused")
check("a reply without plugin_view_restore_attempted is not the set",
      C("pluginWindowControlsViewMenuItem", "zh_CN", "set_param_verified", {"state": "A"}) != "set")
check("plugin_view_restore_attempted False (already in Controls view) is not the set",
      C("pluginWindowControlsViewMenuItem", "zh_CN", "set_param_verified",
        {"state": "A", "plugin_view_restore_attempted": False}) != "set")
expect("plugin_view_restore_attempted True is the set",
       C("pluginWindowControlsViewMenuItem", "zh_CN", "set_param_verified",
         {"state": "A", "plugin_view_restore_attempted": True}), "set")
check("a reply from a call other than set_param_verified is not the set",
      C("pluginWindowControlsViewMenuItem", "zh_CN", "insert_verified",
        {"plugin_view_restore_attempted": True}) != "set")

# regionKindMidi / trackContentExplicit.
expect("a midi region is the set",
       C("regionKindMidi", "ja", "get_regions", {"regions": [{"kind": "audio"}, {"kind": "midi"}]}),
       "set")
expect("no midi region did not reach the set",
       C("regionKindMidi", "ja", "get_regions", {"regions": [{"kind": "audio"}]}), "not_reached")
expect("trackContentExplicit is indistinguishable from its generic fallback",
       C("trackContentExplicit", "ja", "get_regions", {"regions": []}), "indistinguishable")

# The Limits.
for name in R.LIMITS:
    expect(f"{name} is a Limit", C(name, "ko", "none", {}), "not_reachable_via_mcp")

# Every outcome is one of the named ones.
seen = set()
for name in R.SETS:
    for call in ("delete", "create_instrument", "create_audio", ext_call, "set_param_verified",
                 "set_automation:read", "logic://tracks after set_automation:read", "get_regions"):
        for reply in (family, strip, header, {"automationMode": "off"}, {"type": "unknown"},
                      {"reconciled_modal_kind": "delete_confirm"}, {}, None):
            seen.add(C(name, "en", call, reply).split(":")[0])
check("classify returns only the named outcomes", seen <= set(R.OUTCOMES), sorted(seen))

# The excerpt carries the reply's own consumed keys and nothing derived.
big = {"regions": [{"kind": "midi", "name": "x" * 50}] * 40, "state": "A", "noise": 1}
text = R.excerpt("regionKindMidi", big)
check("an excerpt is at most 400 characters", len(text) <= R.EXCERPT_LIMIT, len(text))
check("an excerpt drops keys the classifier does not read", "noise" not in text)
check("an excerpt carries the consumed value itself",
      json.loads(R.excerpt("automationModeRead", {"automationMode": "off"})) == {"automationMode": "off"})
reply_b = {"state": "B", "reason": "retry_exhausted", "reconciled_modal_observation": "incomplete",
           "reconciled_modal_unreadable_reason": "top_level_window_modal_read_failed",
           "reconciled_modal_unreadable_ax_status": -25205, "noise": 1}
check("an excerpt carries a State B reply's own account of why it stopped",
      json.loads(R.excerpt("inspectorChannelStripHelpPrefix", reply_b)) ==
      {"state": "B", "reason": "retry_exhausted", "reconciled_modal_observation": "incomplete",
       "reconciled_modal_unreadable_reason": "top_level_window_modal_read_failed",
       "reconciled_modal_unreadable_ax_status": -25205})

# A failure the classifier cannot name is flagged.
check("a transport error is unnamed", R.unnamed_error({"_transport_error": "EOF"}) is not None)
check("State C without a code is unnamed", R.unnamed_error({"state": "C"}) is not None)
check("State C with a code is named", R.unnamed_error({"state": "C", "error": "x"}) is None)


class Canned:
    """The MCP calls run_locale makes, answered with the shapes the server emits."""

    def __init__(self):
        self.tracks = [{"id": 0, "name": "Inst 1", "type": "software_instrument", "automationMode": "off"},
                       {"id": 1, "name": "Audio 1", "type": "audio", "automationMode": "off"},
                       {"id": 2, "name": "MIDI 3", "type": "external_midi", "automationMode": "off"}]
        self.inserted = False

    def resource(self, uri):
        if uri == "logic://tracks":
            return {"data": [dict(t) for t in self.tracks]}
        return {"data": {"filePath": "/Users/x/Music/Logic/lpm-locale-campaign.logicx"}}

    def tool(self, name, command, params=None):
        params = params or {}
        if command == "create_instrument":
            return dict(family, observed_track_name="Inst 1")
        if command == "create_audio":
            return dict(strip, observed_track_name="Audio 1")
        if command == "create_external_midi":
            return dict(header, observed_track_name="MIDI 3")
        if command == "get_regions":
            return {"regions": [{"trackIndex": 0, "kind": "midi"}]}
        if command == "get_inventory":
            if self.inserted:
                return {"plugins": [{"insert": 1, "occupied": True, "plugin_id": R.COMPRESSOR_ID}]}
            return {"plugins": [{"insert": 1, "occupied": False}]}
        if command == "insert_verified":
            self.inserted = True
            return {"state": "A"}
        if command == "set_param_verified":
            return {"state": "A", "plugin_view_restore_attempted": True}
        if command == "set_automation":
            self.tracks[params["index"]]["automationMode"] = params["mode"]
            return {"state": "A", "observed_mode": params["mode"]}
        if command == "delete":
            return {"state": "A", "reconciled_modal_kind": "delete_confirm"}
        return {"state": "A"}


R.time.sleep = lambda seconds: None
with tempfile.TemporaryDirectory() as scratch:
    rows = R.Rows(os.path.join(scratch, "rows.jsonl"), "0" * 40, "/bin/LogicProMCP")
    R.run_locale(Canned(), rows, "de")
    with open(rows.path, encoding="utf-8") as handle:
        written = [json.loads(line) for line in handle]
got = {(r["set"], r["call"]): r["matched_via"] for r in rows.rows}
check("run_locale writes every row it makes to the JSONL", written == rows.rows)
check("run_locale gives every set a row", R.incomplete_locales(rows.rows, ["de"]) == {},
      R.incomplete_locales(rows.rows, ["de"]))
check("run_locale meets no unnamed error on answered calls", rows.unnamed == [], rows.unnamed)
expect("the canned de delete is the set", got.get(("deleteTracksPrimaryButton", "delete")), "set")
expect("the canned external MIDI header is the fallback",
       got.get(("inspectorChannelStripHelpPrefix", "create_external_midi")), "fallback:observed_header")
expect("the canned touch readback is the set",
       got.get(("automationModeTouch", "logic://tracks after set_automation:touch")), "set")
expect("the canned Controls-view switch is the set",
       got.get(("pluginWindowControlsViewMenuItem", "set_param_verified")), "set")
check("every row carries head_sha and binary",
      all(r["head_sha"] == "0" * 40 and r["binary"] == "/bin/LogicProMCP" for r in rows.rows))

# The row-count check refuses a locale that is short.
short = [r for r in rows.rows if r["set"] != "regionKindMidi"]
incomplete = R.incomplete_locales(short, ["de"])
check("a locale missing one set's rows is refused",
      incomplete.get("de", {}).get("missing_sets") == ["regionKindMidi"], incomplete)
check("a locale with zero rows is refused",
      R.incomplete_locales(rows.rows, ["de", "ko"]).get("ko") == {"rows": 0,
                                                                  "missing_sets": list(R.SETS)})
padded = short + [dict(short[0])]
check("padding with a duplicate row does not stand in for a missing set",
      "de" in R.incomplete_locales(padded, ["de"]))

# The runner refuses to start without the caller's lock.
saved = os.environ.pop("LPM_LIVE_LOCK", None)
try:
    try:
        R.refuse_without_lock()
        check("an unset LPM_LIVE_LOCK is refused", False)
    except SystemExit:
        check("an unset LPM_LIVE_LOCK is refused", True)
    os.environ["LPM_LIVE_LOCK"] = os.path.join(tempfile.gettempdir(), "lpm-904-no-such-lock")
    try:
        R.refuse_without_lock()
        check("an LPM_LIVE_LOCK naming no file is refused", False)
    except SystemExit:
        check("an LPM_LIVE_LOCK naming no file is refused", True)
finally:
    os.environ.pop("LPM_LIVE_LOCK", None)
    if saved is not None:
        os.environ["LPM_LIVE_LOCK"] = saved

print(f"\n{'FAILED' if failed else 'passed'}: {failed} failure(s)")
sys.exit(1 if failed else 0)
