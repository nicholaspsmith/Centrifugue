"""Ableton Live interchange: `.als` Live Sets and `.asd` analysis sidecars.

Live will not read a tempo out of a filename or an ID3 tag, so putting the
detected BPM where Live actually looks means writing one of its own file
formats. Neither is documented; both were reverse-engineered against the
Live 11/12 sets and analysis files already on this machine.

  * `.als` -- gzipped XML. The schema here was read off a real Live set
    rather than guessed, including the non-obvious bit: arrangement clips
    live under TakeLanes/TakeLanes/TakeLane/ClipAutomation/Events, not
    directly under the track.
  * `.asd` -- a binary object graph. `read_warp_markers` is validated (see
    the module test); a writer is deliberately not shipped, and
    `describe_asd_support` explains why.
"""

import gzip
import os
import struct
import zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

# Live 11 schema. Targeting the version there is hard evidence for, rather
# than guessing at Live 12's, and letting Live 12 convert on open -- which
# it does silently for 11 sets. A wrong Live-12 schema fails to open at all.
ALS_MAJOR_VERSION = "5"
ALS_MINOR_VERSION = "11.0_433"
ALS_SCHEMA_CHANGE_COUNT = "6"

# WarpMode 0 is Beats, the right choice for drums and for anything already
# on a grid. Live re-picks per clip if the user changes it.
WARP_MODE_BEATS = 0

TRACK_COLORS = {
    "vocals": 21, "drums": 14, "bass": 26, "other": 6,
    "beat": 14, "instrumental": 6, "piano": 34, "guitar": 12,
}
DEFAULT_TRACK_COLOR = 13


class _Ids:
    """Allocates the document-wide ids Live calls "pointee" ids.

    Live rejects a set with `Invalid Pointee Id` if any AutomationTarget,
    ModulationTarget or Pointee id repeats -- they share one namespace and
    every occurrence must be unique. Verified against a real set: 5285
    AutomationTargets and 3631 ModulationTargets, all distinct, with
    NextPointeeId exactly one past the maximum.
    """

    def __init__(self, start=8):
        self._next = start

    def take(self):
        value = self._next
        self._next += 1
        return value

    @property
    def limit(self):
        """What NextPointeeId must be: past everything handed out."""
        return self._next + 1


def _el(tag, value):
    return f'<{tag} Value={quoteattr(str(value))} />'


def _bool(tag, value):
    return _el(tag, "true" if value else "false")


def _target(tag, ids):
    """An automation/modulation target: unique id plus a LockEnvelope child."""
    return f'<{tag} Id="{ids.take()}"><LockEnvelope Value="0" /></{tag}>'


def _switch(tag, ids, manual=True):
    """An On/Speaker-style boolean with its MIDI thresholds."""
    return "".join([
        f"<{tag}>", _el("LomId", 0), _bool("Manual", manual),
        _target("AutomationTarget", ids),
        '<MidiCCOnOffThresholds><Min Value="64" /><Max Value="127" />'
        "</MidiCCOnOffThresholds>",
        f"</{tag}>",
    ])


def _param(tag, manual, ids, midi_min=None, midi_max=None, modulation=True):
    """A continuous mixer parameter (Pan, Volume, Tempo, ...)."""
    parts = [f"<{tag}>", _el("LomId", 0), _el("Manual", manual)]
    if midi_min is not None:
        parts.append(f'<MidiControllerRange><Min Value="{midi_min}" />'
                     f'<Max Value="{midi_max}" /></MidiControllerRange>')
    parts.append(_target("AutomationTarget", ids))
    if modulation:
        parts.append(_target("ModulationTarget", ids))
    parts.append(f"</{tag}>")
    return "".join(parts)


def beats_for(duration_seconds, bpm):
    """How many beats a clip of this length occupies at this tempo."""
    if not duration_seconds or not bpm or bpm <= 0:
        return 0.0
    return float(duration_seconds) * float(bpm) / 60.0


def _file_ref(path, project_root=None):
    """Locate the sample both absolutely and relative to the set."""
    path = Path(path)
    absolute = str(Path(os.path.abspath(str(path))))
    try:
        relative = str(Path(absolute).relative_to(
            Path(os.path.abspath(str(project_root))))) if project_root else path.name
    except (ValueError, OSError):
        relative = path.name

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    crc = 0
    try:
        with open(path, "rb") as handle:
            crc = zlib.crc32(handle.read(16384)) & 0xFFFF
    except OSError:
        pass

    return "".join([
        "<FileRef>",
        # 3 = relative to the Live Set's own folder, which is where we write.
        _el("RelativePathType", 3),
        _el("RelativePath", relative),
        _el("Path", absolute),
        _el("Type", 2),
        _el("LivePackName", ""),
        _el("LivePackId", ""),
        _el("OriginalFileSize", size),
        _el("OriginalCrc", crc),
        "</FileRef>",
    ])


def _warp_markers(duration_seconds, bpm):
    """A straight, constant-tempo warp.

    Two markers define a constant tempo; Live interpolates between them and
    extrapolates past the last. A third just after the origin matches what
    Live writes itself and stops the very start drifting.
    """
    total_beats = beats_for(duration_seconds, bpm) or 4.0
    seconds_per_beat = 60.0 / float(bpm)
    markers = [(0.0, 0.0), (seconds_per_beat, 1.0),
               (float(duration_seconds or 0.0), total_beats)]

    out = ["<WarpMarkers>"]
    for index, (seconds, beats) in enumerate(markers):
        out.append(
            f'<WarpMarker Id="{index}" SecTime="{seconds!r}" BeatTime="{beats!r}" />')
    out.append("</WarpMarkers>")
    return "".join(out)


def _mixer(ids, tempo=None):
    """The mixer chain. `tempo` is set only for the master track.

    Tempo lives *inside* Mixer, not beside it -- a set with Tempo one level
    up loads without complaint and then ignores the value entirely.
    """
    parts = [
        "<Mixer>", _el("LomId", 0), _el("LomIdView", 0), _bool("IsExpanded", True),
        _switch("On", ids),
        _el("ModulationSourceCount", 0),
        '<ParametersListWrapper LomId="0" />',
        f'<Pointee Id="{ids.take()}" />',
        _el("LastSelectedTimeableIndex", 0),
        _el("LastSelectedClipEnvelopeIndex", 0),
        "<LastPresetRef><Value /></LastPresetRef>",
        "<LockedScripts />", _bool("IsFolded", False),
        _bool("ShouldShowPresetName", False), _el("UserName", ""),
        _el("Annotation", ""),
        "<SourceContext><Value /></SourceContext>",
        "<Sends />",
        _switch("Speaker", ids),
        _bool("SoloSink", False), _el("PanMode", 0),
        _param("Pan", 0, ids, -1, 1),
        _param("SplitStereoPanL", -1, ids, -1, 1),
        _param("SplitStereoPanR", 1, ids, -1, 1),
        _param("Volume", 1, ids, "0.0003162277571", "1.99526238"),
        _el("ViewStateSesstionTrackWidth", 93),
        "<CrossFadeState>", _el("LomId", 0), _el("Manual", 1),
        _target("AutomationTarget", ids), "</CrossFadeState>",
        '<SendsListWrapper LomId="0" />',
    ]
    if tempo is not None:
        parts += [
            _param("Tempo", tempo, ids, 60, 200),
            # 201 is Live's enum for 4/4, not a numerator.
            "<TimeSignature>", _el("LomId", 0), _el("Manual", 201),
            _target("AutomationTarget", ids), "</TimeSignature>",
            _param("GlobalGrooveAmount", 100, ids, 0, "131.25"),
            _param("CrossFade", 0, ids, -1, 1),
            _el("TempoAutomationViewBottom", 60),
            _el("TempoAutomationViewTop", 200),
        ]
    parts.append("</Mixer>")
    return "".join(parts)


def _sequencer(tag, ids, monitoring, clip=None, concrete=None):
    """MainSequencer / FreezeSequencer -- identical but for monitoring.

    `clip` puts an AudioClip in Session slot 0, which is where a `.alc`
    Live Clip keeps its clip. A `.als` leaves the slot empty and puts the
    clip in the track's Arrangement TakeLanes instead.

    `concrete` names the polymorphic subclass element Live wraps the
    children in. Exactly one sequencer in the document needs it -- the
    master track's FreezeSequencer, which is written as
    `<FreezeSequencer><AudioSequencer Id="0">...`. Surveyed across 1,767
    Live-written `.als` and `.alc` files spanning Live 9 to 12: every one
    wraps that sequencer and no other. Omitting the wrapper is not a
    tolerated variation -- Live refuses the whole document with
    "Unknown class 'LomId'" and will not open it.
    """
    slots = "<ClipSlotList />" if clip is None else "".join([
        '<ClipSlotList><ClipSlot Id="0">', _el("LomId", 0),
        "<ClipSlot><Value>", clip, "</Value></ClipSlot>",
        _bool("HasStop", True), _bool("NeedRefreeze", True),
        "</ClipSlot></ClipSlotList>",
    ])
    open_tag = f"<{tag}>" if concrete is None else f'<{tag}><{concrete} Id="0">'
    close_tag = f"</{tag}>" if concrete is None else f"</{concrete}></{tag}>"
    return "".join([
        open_tag, _el("LomId", 0), _el("LomIdView", 0), _bool("IsExpanded", True),
        _switch("On", ids),
        _el("ModulationSourceCount", 0),
        '<ParametersListWrapper LomId="0" />',
        f'<Pointee Id="{ids.take()}" />',
        _el("LastSelectedTimeableIndex", 0),
        _el("LastSelectedClipEnvelopeIndex", 0),
        "<LastPresetRef><Value /></LastPresetRef>",
        "<LockedScripts />", _bool("IsFolded", False),
        _bool("ShouldShowPresetName", True), _el("UserName", ""),
        _el("Annotation", ""),
        "<SourceContext><Value /></SourceContext>",
        slots,
        _el("MonitoringEnum", monitoring),
        "<Sample><ArrangerAutomation><Events />"
        "<AutomationTransformViewState><IsTransformPending Value=\"false\" />"
        "<TimeAndValueTransforms /></AutomationTransformViewState>"
        "</ArrangerAutomation></Sample>",
        _target("VolumeModulationTarget", ids),
        _target("TranspositionModulationTarget", ids),
        _target("GrainSizeModulationTarget", ids),
        _target("FluxModulationTarget", ids),
        _target("SampleOffsetModulationTarget", ids),
        _el("PitchViewScrollPosition", -1073741824),
        _el("SampleOffsetModulationScrollPosition", -1073741824),
        '<Recorder><IsArmed Value="false" /><TakeCounter Value="1" /></Recorder>',
        close_tag,
    ])


def _routing(tag, target, upper, lower):
    return (f"<{tag}><Target Value={quoteattr(target)} />"
            f"<UpperDisplayString Value={quoteattr(upper)} />"
            f"<LowerDisplayString Value={quoteattr(lower)} /></{tag}>")


def _automation_lanes():
    return ('<AutomationLanes><AutomationLanes><AutomationLane Id="0">'
            '<SelectedDevice Value="0" /><SelectedEnvelope Value="0" />'
            '<IsContentSelectedInDocument Value="false" />'
            '<LaneHeight Value="68" /></AutomationLane></AutomationLanes>'
            '<AreAdditionalAutomationLanesFolded Value="false" /></AutomationLanes>'
            '<ClipEnvelopeChooserViewState><SelectedDevice Value="0" />'
            '<SelectedEnvelope Value="0" />'
            '<PreferModulationVisible Value="false" />'
            '</ClipEnvelopeChooserViewState>')


def _audio_clip(name, path, duration_seconds, bpm, project_root, is_tempo_master):
    total_beats = beats_for(duration_seconds, bpm) or 4.0
    return "".join([
        '<AudioClip Id="0" Time="0">',
        _el("LomId", 0), _el("LomIdView", 0),
        _el("CurrentStart", 0), _el("CurrentEnd", total_beats),
        "<Loop>", _el("LoopStart", 0), _el("LoopEnd", total_beats),
        _el("StartRelative", 0), _bool("LoopOn", False),
        _el("OutMarker", total_beats), _el("HiddenLoopStart", 0),
        _el("HiddenLoopEnd", total_beats), "</Loop>",
        _el("Name", name), _el("Annotation", ""),
        _el("Color", TRACK_COLORS.get(name, DEFAULT_TRACK_COLOR)),
        _el("LaunchMode", 0), _el("LaunchQuantisation", 0),
        '<TimeSignature><TimeSignatures><RemoteableTimeSignature Id="0">'
        '<Numerator Value="4" /><Denominator Value="4" /><Time Value="0" />'
        "</RemoteableTimeSignature></TimeSignatures></TimeSignature>",
        "<Envelopes><Envelopes /></Envelopes>",
        '<ScrollerTimePreserver><LeftTime Value="0" />'
        f'<RightTime Value="{total_beats!r}" /></ScrollerTimePreserver>',
        '<TimeSelection><AnchorTime Value="0" /><OtherTime Value="0" />'
        "</TimeSelection>",
        _bool("Legato", False), _bool("Ram", False),
        '<GrooveSettings><GrooveId Value="-1" /></GrooveSettings>',
        _bool("Disabled", False), _el("VelocityAmount", 0),
        '<FollowAction><FollowTime Value="4" /><IsLinked Value="true" />'
        '<LoopIterations Value="1" /><FollowActionA Value="4" />'
        '<FollowActionB Value="0" /><FollowChanceA Value="1" />'
        '<FollowChanceB Value="0" /><JumpIndexA Value="0" />'
        '<JumpIndexB Value="0" /><FollowActionEnabled Value="false" />'
        "</FollowAction>",
        '<Grid><FixedNumerator Value="1" /><FixedDenominator Value="16" />'
        '<GridIntervalPixel Value="20" /><Ntoles Value="2" />'
        '<SnapToGrid Value="true" /><Fixed Value="false" /></Grid>',
        _el("FreezeStart", 0), _el("FreezeEnd", 0),
        _bool("IsWarped", True), _el("TakeId", 1),
        "<SampleRef>", _file_ref(path, project_root),
        _el("LastModDate", 0), "<SourceContext />",
        _el("SampleUsageHint", 0),
        _el("DefaultDuration", 0), _el("DefaultSampleRate", 0),
        "</SampleRef>",
        '<Onsets><UserOnsets /><HasUserOnsets Value="false" /></Onsets>',
        _el("WarpMode", WARP_MODE_BEATS),
        _el("GranularityTones", 30), _el("GranularityTexture", 65),
        _el("FluctuationTexture", 25), _el("TransientResolution", 6),
        _el("TransientLoopMode", 2), _el("TransientEnvelope", 100),
        _el("ComplexProFormants", 100), _el("ComplexProEnvelope", 128),
        _bool("Sync", True), _bool("HiQ", True),
        _bool("Fade", True),
        '<Fades><FadeInLength Value="0" /><FadeOutLength Value="0" />'
        '<ClipFadesAreInitialized Value="true" /></Fades>',
        _el("PitchCoarse", 0), _el("PitchFine", 0), _el("SampleVolume", 1),
        _el("MarkerDensity", 2), _el("AutoWarpTolerance", 0),
        _warp_markers(duration_seconds, bpm),
        "<SavedWarpMarkersForStretched />",
        _bool("MarkersGenerated", True),
        _bool("IsSongTempoMaster", is_tempo_master),
        "</AudioClip>",
    ])


def _audio_track(ids, name, path, duration_seconds, bpm, project_root,
                 is_tempo_master, in_session=False):
    """One track carrying one stem.

    `in_session` puts the clip in Session slot 0 -- what a `.alc` needs --
    leaving the Arrangement empty. The default puts it in the Arrangement,
    which is what a `.als` needs.
    """
    clip = _audio_clip(name, path, duration_seconds, bpm, project_root,
                       is_tempo_master)
    take_lanes = (
        '<TakeLanes><TakeLanes /><AreTakeLanesFolded Value="true" /></TakeLanes>'
        if in_session else "".join([
            '<TakeLanes><TakeLanes><TakeLane Id="0">',
            "<ClipAutomation><Events>", clip, "</Events></ClipAutomation>",
            _bool("Muted", False), _el("VerticalScaling", 1),
            "</TakeLane></TakeLanes>",
            _bool("AreTakeLanesFolded", True), "</TakeLanes>",
        ]))
    return "".join([
        f'<AudioTrack Id="{ids.take()}">',
        _el("LomId", 0), _el("LomIdView", 0),
        _bool("IsContentSelectedInDocument", False),
        _el("PreferredContentViewMode", 0),
        '<TrackDelay><Value Value="0" />'
        '<IsValueSampleBased Value="false" /></TrackDelay>',
        f"<Name><EffectiveName Value={quoteattr(name)} />"
        f"<UserName Value={quoteattr(name)} /><Annotation Value=\"\" />"
        f'<MemorizedFirstClipName Value="" /></Name>',
        _el("Color", TRACK_COLORS.get(name, DEFAULT_TRACK_COLOR)),
        "<AutomationEnvelopes><Envelopes /></AutomationEnvelopes>",
        _el("TrackGroupId", -1), _bool("TrackUnfolded", True),
        '<DevicesListWrapper LomId="0" />',
        '<ClipSlotsListWrapper LomId="0" />',
        _el("ViewData", "{}"),
        take_lanes,
        _el("LinkedTrackGroupId", -1),
        _el("SavedPlayingSlot", -1), _el("SavedPlayingOffset", 0),
        _bool("Freeze", False), _el("VelocityDetail", 0),
        _bool("NeedArrangerRefreeze", True), _el("PostProcessFreezeClips", 0),
        "<DeviceChain>",
        _automation_lanes(),
        _routing("AudioInputRouting", "AudioIn/External/S0", "Ext. In", "1/2"),
        _routing("MidiInputRouting", "MidiIn/External.All/-1", "Ext: All Ins", ""),
        _routing("AudioOutputRouting", "AudioOut/Master", "Master", ""),
        _routing("MidiOutputRouting", "MidiOut/None", "None", ""),
        _mixer(ids),
        _sequencer("MainSequencer", ids, monitoring=2,
                   clip=clip if in_session else None),
        _sequencer("FreezeSequencer", ids, monitoring=1),
        "<DeviceChain><Devices /><SignalModulations /></DeviceChain>",
        "</DeviceChain>",
        "</AudioTrack>",
    ])


def _master_track(ids, bpm):
    return "".join([
        "<MasterTrack>",
        _el("LomId", 0), _el("LomIdView", 0),
        _bool("IsContentSelectedInDocument", False),
        _el("PreferredContentViewMode", 0),
        '<TrackDelay><Value Value="0" />'
        '<IsValueSampleBased Value="false" /></TrackDelay>',
        '<Name><EffectiveName Value="Master" /><UserName Value="" />'
        '<Annotation Value="" /><MemorizedFirstClipName Value="" /></Name>',
        _el("Color", -1),
        "<AutomationEnvelopes><Envelopes /></AutomationEnvelopes>",
        _el("TrackGroupId", -1), _bool("TrackUnfolded", False),
        '<DevicesListWrapper LomId="0" />',
        '<ClipSlotsListWrapper LomId="0" />',
        _el("ViewData", "{}"),
        "<DeviceChain>",
        _automation_lanes(),
        _routing("AudioInputRouting", "AudioIn/External/S0", "Ext. In", "1/2"),
        _routing("MidiInputRouting", "MidiIn/External.All/-1", "Ext: All Ins", ""),
        _routing("AudioOutputRouting", "AudioOut/External/S0", "Ext. Out", "1/2"),
        _routing("MidiOutputRouting", "MidiOut/None", "None", ""),
        _mixer(ids, tempo=bpm),
        # The master track has no MainSequencer -- only a FreezeSequencer,
        # and that one is written wrapped in its concrete AudioSequencer.
        _sequencer("FreezeSequencer", ids, monitoring=0,
                   concrete="AudioSequencer"),
        "<DeviceChain><Devices /><SignalModulations /></DeviceChain>",
        "</DeviceChain>",
        "</MasterTrack>",
    ])


def _pre_hear_track(ids):
    return "".join([
        "<PreHearTrack>",
        _el("LomId", 0), _el("LomIdView", 0),
        _bool("IsContentSelectedInDocument", False),
        _el("PreferredContentViewMode", 0),
        '<TrackDelay><Value Value="0" />'
        '<IsValueSampleBased Value="false" /></TrackDelay>',
        '<Name><EffectiveName Value="Master" /><UserName Value="" />'
        '<Annotation Value="" /><MemorizedFirstClipName Value="" /></Name>',
        _el("Color", -1),
        "<AutomationEnvelopes><Envelopes /></AutomationEnvelopes>",
        _el("TrackGroupId", -1), _bool("TrackUnfolded", False),
        '<DevicesListWrapper LomId="0" />',
        '<ClipSlotsListWrapper LomId="0" />',
        _el("ViewData", "{}"),
        "<DeviceChain>",
        _automation_lanes(),
        _routing("AudioInputRouting", "AudioIn/External/S0", "Ext. In", "1/2"),
        _routing("MidiInputRouting", "MidiIn/External.All/-1", "Ext: All Ins", ""),
        _routing("AudioOutputRouting", "AudioOut/None", "None", ""),
        _routing("MidiOutputRouting", "MidiOut/None", "None", ""),
        _mixer(ids),
        # No sequencers here at all: Live writes the pre-hear track's
        # DeviceChain as Mixer then DeviceChain, nothing between.
        "<DeviceChain><Devices /><SignalModulations /></DeviceChain>",
        "</DeviceChain>",
        "</PreHearTrack>",
    ])


def _live_set_document(tracks, ids, tempo, key):
    """Wrap already-built tracks in the LiveSet document.

    Shared by `.als` and `.alc`: the two formats differ only in how
    many tracks they carry and where the clip sits inside one, not in
    the document around them.
    """
    master = _master_track(ids, tempo)
    pre_hear = _pre_hear_track(ids)

    annotation = f"Centrifugue -- {tempo:g} BPM"
    if key:
        annotation += f", {key}"

    return "".join([
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        f'<Ableton MajorVersion="{ALS_MAJOR_VERSION}" '
        f'MinorVersion="{ALS_MINOR_VERSION}" '
        f'SchemaChangeCount="{ALS_SCHEMA_CHANGE_COUNT}" '
        f'Creator="Centrifugue" Revision="">',
        "<LiveSet>",
        # Must sit past every id handed out above, so it is emitted last.
        _el("NextPointeeId", ids.limit),
        _el("OverwriteProtectionNumber", 2816),
        _el("LomId", 0), _el("LomIdView", 0),
        "<Tracks>", tracks, "</Tracks>",
        master, pre_hear,
        "<SendsPre />",
        '<Scenes><Scene Id="0"><FollowAction><FollowTime Value="4" />'
        '<IsLinked Value="true" /><LoopIterations Value="1" />'
        '<FollowActionA Value="4" /><FollowActionB Value="0" />'
        '<FollowChanceA Value="1" /><FollowChanceB Value="0" />'
        '<JumpIndexA Value="0" /><JumpIndexB Value="0" />'
        '<FollowActionEnabled Value="false" /></FollowAction>'
        '<Name Value="" /><Annotation Value="" /><Color Value="-1" />'
        '<Tempo Value="-1" /><IsTempoEnabled Value="false" />'
        '<TimeSignatureId Value="-1" /><IsTimeSignatureEnabled Value="false" />'
        '<LomId Value="0" /><ClipSlotsListWrapper LomId="0" />'
        "</Scene></Scenes>",
        '<Transport><PhaseNudgeTempo Value="100" /><LoopOn Value="false" />'
        '<LoopStart Value="0" /><LoopLength Value="16" />'
        '<LoopIsSongStart Value="true" /><CurrentTime Value="0" />'
        '<PunchIn Value="false" /><PunchOut Value="false" />'
        '<MetronomeTickDuration Value="0" /><DrawMode Value="false" />'
        "</Transport>",
        "<SongMasterValues><SessionScrollerPos><X Value=\"0\" />"
        '<Y Value="0" /></SessionScrollerPos></SongMasterValues>',
        "<SignalModulations />",
        _el("GlobalQuantisation", 4), _el("AutoQuantisation", 0),
        '<Grid><FixedNumerator Value="1" /><FixedDenominator Value="16" />'
        '<GridIntervalPixel Value="20" /><Ntoles Value="2" />'
        '<SnapToGrid Value="true" /><Fixed Value="false" /></Grid>',
        '<ScaleInformation><RootNote Value="0" />'
        '<Name Value="Major" /></ScaleInformation>',
        _bool("InKey", False), _el("SmpteFormat", 0),
        '<TimeSelection><AnchorTime Value="0" />'
        '<OtherTime Value="0" /></TimeSelection>',
        "<SequencerNavigator><BeatTimeHelper>"
        '<CurrentZoom Value="0.5" /></BeatTimeHelper>'
        '<ScrollerPos><X Value="0" /><Y Value="0" /></ScrollerPos>'
        '<ClientSize><X Value="1" /><Y Value="1" /></ClientSize>'
        "</SequencerNavigator>",
        _el("ViewStateExtendedClipProperties", 0),
        _bool("IsContentSplitterOpen", False),
        _bool("IsExpressionSplitterOpen", False),
        _el("Annotation", annotation),
        "</LiveSet>",
        "</Ableton>",
    ])


def build_als(stems, bpm, project_root=None, key=None):
    """Build a Live Set XML document placing each stem on its own track.

    `stems` is an ordered sequence of (name, path, duration_seconds). The
    first track is marked song-tempo master so Live adopts the detected
    tempo instead of re-guessing it.
    """
    if not stems:
        raise ValueError("at least one stem is required")
    tempo = float(bpm) if bpm else 120.0

    ids = _Ids()
    tracks = "".join(
        _audio_track(ids, name, path, duration, tempo, project_root,
                     is_tempo_master=(index == 0))
        for index, (name, path, duration) in enumerate(stems))
    return _live_set_document(tracks, ids, tempo, key)


def write_als(path, stems, bpm, project_root=None, key=None):
    """Write a gzipped Live Set. Returns the path written."""
    path = Path(path)
    xml = build_als(stems, bpm, project_root=project_root, key=key)
    # gzip.compress rather than GzipFile: GzipFile stamps the source filename
    # and mtime into the header, so the same set written to two paths would
    # differ byte-for-byte. mtime=0 pins the other half of that.
    path.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))
    return path


def build_alc(name, path, duration_seconds, bpm, project_root=None, key=None):
    """Build a Live Clip document for a single stem.

    A `.alc` is the same schema as a `.als`, cut down to one track whose
    clip sits in Session slot 0. It exists because of what Live does *not*
    read when a bare audio file is dragged in: not the filename, not the
    BPM tag, not the sibling `.als`. Only the `.asd` sidecar, which we do
    not write (see `describe_asd_support`). With nothing to read, Live runs
    its own tempo estimate per file -- and on a stem with sparse transients
    it lands somewhere else entirely, so two stems cut from one song import
    at two different tempos and drift apart.

    Dragging the `.alc` hands Live the markers instead of letting it guess.
    Every stem from one render carries identical markers, so they stay
    locked to each other, and `IsSongTempoMaster` stays false so the clip
    follows whatever tempo the destination Set is already at.
    """
    tempo = float(bpm) if bpm else 120.0
    ids = _Ids()
    track = _audio_track(ids, name, path, duration_seconds, tempo,
                         project_root, is_tempo_master=False, in_session=True)
    return _live_set_document(track, ids, tempo, key)


def write_alc(path, name, sample_path, duration_seconds, bpm,
              project_root=None, key=None):
    """Write a gzipped Live Clip. Returns the path written."""
    path = Path(path)
    xml = build_alc(name, sample_path, duration_seconds, bpm,
                    project_root=project_root, key=key)
    # mtime=0 and gzip.compress for the same reason as write_als: a stamped
    # header would make the same clip differ byte-for-byte between renders.
    path.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))
    return path


# --------------------------------------------------------------------------
# .asd -- binary analysis sidecars
# --------------------------------------------------------------------------

# Validated against 3,741 warped .asd files: the literal `WarpMarker`, then
# 14 bytes, then two little-endian doubles (seconds, beats).
_ASD_MARKER = b"WarpMarker"
_ASD_MARKER_GAP = 14


def read_warp_markers(path):
    """Extract (seconds, beats) warp markers from a Live .asd file.

    Returns [] for an analysed-but-never-warped file, which is what Live
    writes on plain import.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []

    markers = []
    index = -1
    while True:
        index = data.find(_ASD_MARKER, index + 1)
        if index < 0:
            break
        start = index + _ASD_MARKER_GAP
        if start + 16 > len(data):
            break
        seconds, beats = struct.unpack("<dd", data[start:start + 16])
        markers.append((seconds, beats))
    return markers


def tempo_from_asd(path):
    """Infer the tempo Live warped a sample to, or None."""
    markers = read_warp_markers(path)
    unique = []
    for marker in markers:
        if not unique or marker != unique[-1]:
            unique.append(marker)
    if len(unique) < 2:
        return None
    (first_seconds, first_beats), (last_seconds, last_beats) = unique[0], unique[-1]
    if last_seconds == first_seconds:
        return None
    return (last_beats - first_beats) / (last_seconds - first_seconds) * 60.0


def describe_asd_support():
    """Why we read .asd files but do not write them.

    Kept as code rather than a comment so the CLI can print it verbatim
    when a user asks for .asd output.
    """
    return (
        "Centrifugue reads .asd warp markers but does not write them.\n"
        "\n"
        "An .asd is not a flat record: it is a serialised object graph with a\n"
        "type dictionary (entries look like <u32 char count><UTF-16LE field\n"
        "name><0x0000><u8 len><ASCII type name>, e.g. ExtraLength ->\n"
        "RemoteableInt) followed by instance data, then a large waveform\n"
        "overview. Inserting a warp-marker block means rebuilding that graph\n"
        "and its type table correctly; a malformed file makes Live mis-warp\n"
        "silently rather than report an error.\n"
        "\n"
        "The .als Live Set carries the same warp markers in a documented,\n"
        "verifiable form and achieves the same result, so it is used instead.\n"
    )
