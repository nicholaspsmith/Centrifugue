"""Live Set generation and .asd warp-marker reading."""

import gzip
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

import centrifugue_ableton as ableton


def _set_for(stems, bpm=124.0, **kwargs):
    return ET.fromstring(ableton.build_als(stems, bpm, **kwargs))


STEMS = [("drums", "/tmp/drums.flac", 180.0), ("vocals", "/tmp/vocals.flac", 180.0)]


def test_beats_for_converts_seconds_at_tempo():
    assert ableton.beats_for(60.0, 120.0) == 120.0
    assert ableton.beats_for(180.0, 124.0) == pytest.approx(372.0)


def test_beats_for_rejects_nonsense():
    assert ableton.beats_for(None, 120) == 0.0
    assert ableton.beats_for(60, 0) == 0.0


def test_build_als_sets_the_detected_tempo():
    # Tempo lives INSIDE Mixer. A set with it one level up loads fine and
    # then ignores the value, so assert the exact path Live reads.
    root = _set_for(STEMS)
    tempo = root.find("LiveSet/MasterTrack/DeviceChain/Mixer/Tempo/Manual")
    assert float(tempo.attrib["Value"]) == 124.0


def test_tempo_is_not_a_sibling_of_the_mixer():
    root = _set_for(STEMS)
    assert root.find("LiveSet/MasterTrack/DeviceChain/Tempo") is None


# Every id in this namespace must be unique document-wide or Live refuses the
# set with "Invalid Pointee Id".
_POINTEE_TAGS = ("AutomationTarget", "ModulationTarget", "Pointee",
                 "VolumeModulationTarget", "TranspositionModulationTarget",
                 "GrainSizeModulationTarget", "FluxModulationTarget",
                 "SampleOffsetModulationTarget", "AudioTrack")


def _pointee_ids(root):
    return [int(e.attrib["Id"]) for tag in _POINTEE_TAGS
            for e in root.iter(tag) if "Id" in e.attrib]


def test_pointee_ids_are_unique():
    ids = _pointee_ids(_set_for(STEMS))
    assert ids
    assert len(ids) == len(set(ids))


def test_pointee_ids_stay_unique_as_tracks_are_added():
    many = [(f"stem{n}", f"/tmp/s{n}.flac", 60.0) for n in range(6)]
    ids = _pointee_ids(_set_for(many))
    assert len(ids) == len(set(ids))


def test_next_pointee_id_exceeds_every_allocated_id():
    root = _set_for(STEMS)
    declared = int(root.find("LiveSet/NextPointeeId").attrib["Value"])
    assert declared > max(_pointee_ids(root))


def test_pointee_uses_an_id_not_a_value():
    root = _set_for(STEMS)
    pointees = list(root.iter("Pointee"))
    assert pointees
    assert all("Id" in p.attrib and "Value" not in p.attrib for p in pointees)


def test_list_wrappers_use_a_lomid_attribute():
    # <DevicesListWrapper Value="0"/> is rejected; the attribute is LomId.
    root = _set_for(STEMS)
    for tag in ("DevicesListWrapper", "ClipSlotsListWrapper",
                "ParametersListWrapper", "SendsListWrapper"):
        elements = list(root.iter(tag))
        assert elements, tag
        assert all("LomId" in e.attrib and "Value" not in e.attrib
                   for e in elements), tag


def test_mixer_carries_the_parameters_live_expects():
    root = _set_for(STEMS)
    mixer = root.find("LiveSet/Tracks/AudioTrack/DeviceChain/Mixer")
    for tag in ("SplitStereoPanL", "SplitStereoPanR", "CrossFadeState",
                "SendsListWrapper", "Speaker", "Volume", "Pan"):
        assert mixer.find(tag) is not None, tag


def test_on_switches_declare_midi_thresholds():
    root = _set_for(STEMS)
    on = root.find("LiveSet/Tracks/AudioTrack/DeviceChain/Mixer/On")
    assert on.find("MidiCCOnOffThresholds/Min") is not None


def test_master_track_has_no_main_sequencer():
    root = _set_for(STEMS)
    chain = root.find("LiveSet/MasterTrack/DeviceChain")
    assert chain.find("MainSequencer") is None
    assert chain.find("FreezeSequencer") is not None


def test_build_als_puts_each_stem_on_its_own_named_track():
    root = _set_for(STEMS)
    names = [t.find("Name/EffectiveName").attrib["Value"]
             for t in root.findall("LiveSet/Tracks/AudioTrack")]
    assert names == ["drums", "vocals"]


def test_arrangement_clips_sit_where_live_looks_for_them():
    root = _set_for(STEMS)
    clip = root.find("LiveSet/Tracks/AudioTrack/TakeLanes/TakeLanes/TakeLane"
                     "/ClipAutomation/Events/AudioClip")
    assert clip is not None
    assert clip.find("IsWarped").attrib["Value"] == "true"


def test_only_the_first_track_masters_the_tempo():
    root = _set_for(STEMS)
    flags = [c.find("IsSongTempoMaster").attrib["Value"]
             for c in root.findall(".//AudioClip")]
    assert flags == ["true", "false"]


def test_warp_markers_encode_the_tempo():
    root = _set_for(STEMS)
    markers = [(float(m.attrib["SecTime"]), float(m.attrib["BeatTime"]))
               for m in root.findall(".//AudioClip/WarpMarkers/WarpMarker")]
    (first_sec, first_beat), (last_sec, last_beat) = markers[0], markers[-1]
    implied = (last_beat - first_beat) / (last_sec - first_sec) * 60
    assert implied == pytest.approx(124.0)


def test_no_duplicate_elements_in_a_track():
    # Live reads the first match; a duplicated tag silently shadows the real one.
    root = _set_for(STEMS)
    track = root.find("LiveSet/Tracks/AudioTrack")
    duplicates = {tag: n for tag, n in Counter(c.tag for c in track).items() if n > 1}
    assert duplicates == {}


def test_no_duplicate_elements_in_the_live_set():
    root = _set_for(STEMS)
    live_set = root.find("LiveSet")
    duplicates = {tag: n for tag, n in Counter(c.tag for c in live_set).items() if n > 1}
    assert duplicates == {}


def test_sample_reference_carries_both_paths():
    root = _set_for(STEMS)
    ref = root.find(".//SampleRef/FileRef")
    assert ref.find("Path").attrib["Value"].endswith("drums.flac")
    assert ref.find("RelativePath").attrib["Value"] == "drums.flac"


def test_build_als_rejects_an_empty_stem_list():
    with pytest.raises(ValueError):
        ableton.build_als([], 124.0)


def test_write_als_is_gzipped_and_reparses(tmp_path):
    target = ableton.write_als(tmp_path / "set.als", STEMS, 124.0)
    root = ET.fromstring(gzip.open(target).read())
    assert root.tag == "Ableton"


def test_write_als_is_reproducible(tmp_path):
    first = ableton.write_als(tmp_path / "a.als", STEMS, 124.0).read_bytes()
    second = ableton.write_als(tmp_path / "b.als", STEMS, 124.0).read_bytes()
    assert first == second


# --------------------------------------------------------------------------
# Track shape. Live rejects a whole document over these, and the rest of the
# suite cannot see it: the XML stays well-formed and every invariant holds.
# Surveyed across 1,767 Live-written .als/.alc files, Live 9 through 12.
# --------------------------------------------------------------------------


def _both_documents():
    return {"als": _set_for(STEMS),
            "alc": ET.fromstring(ableton.build_alc(
                "drums", "/tmp/drums.flac", 180.0, 124.0))}


def test_master_freeze_sequencer_is_wrapped_in_its_concrete_class():
    # Live writes <FreezeSequencer><AudioSequencer Id="0">. Emitting the
    # children bare makes it refuse the document: "Unknown class 'LomId'".
    for label, root in _both_documents().items():
        seq = root.find("LiveSet/MasterTrack/DeviceChain/FreezeSequencer")
        assert seq is not None, label
        assert [c.tag for c in seq] == ["AudioSequencer"], label
        assert seq.find("AudioSequencer").attrib["Id"] == "0", label


def test_master_track_has_no_freeze_sequencer_children_of_its_own():
    for label, root in _both_documents().items():
        seq = root.find("LiveSet/MasterTrack/DeviceChain/FreezeSequencer")
        assert seq.find("LomId") is None, label


def test_pre_hear_track_carries_no_sequencer():
    # Real files go Mixer then DeviceChain with nothing between.
    for label, root in _both_documents().items():
        chain = root.find("LiveSet/PreHearTrack/DeviceChain")
        tags = [c.tag for c in chain]
        assert "MainSequencer" not in tags, label
        assert "FreezeSequencer" not in tags, label


def test_audio_track_sequencers_stay_unwrapped():
    # Only the master track's freeze sequencer takes the wrapper; an audio
    # track's two are written bare in all 215 real tracks surveyed.
    for label, root in _both_documents().items():
        for track in root.findall("LiveSet/Tracks/AudioTrack"):
            for tag in ("MainSequencer", "FreezeSequencer"):
                seq = track.find(f"DeviceChain/{tag}")
                assert seq is not None, (label, tag)
                assert seq.find("AudioSequencer") is None, (label, tag)
                assert seq.find("LomId") is not None, (label, tag)


# --------------------------------------------------------------------------
# .alc -- Live Clips, the format that survives a drag into an existing Set
# --------------------------------------------------------------------------

_SESSION_CLIP = ("LiveSet/Tracks/AudioTrack/DeviceChain/MainSequencer"
                 "/ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip")


def _clip_for(name="drums", path="/tmp/drums.flac", duration=180.0, bpm=124.0,
              **kwargs):
    return ET.fromstring(ableton.build_alc(name, path, duration, bpm, **kwargs))


def test_alc_keeps_its_clip_in_the_session_slot():
    # A .als hides its clip in TakeLanes; a .alc must use the Session slot,
    # and Live silently ignores a clip in the wrong place.
    assert _clip_for().find(_SESSION_CLIP) is not None


def test_alc_leaves_the_arrangement_empty():
    assert _clip_for().find(".//TakeLane") is None


def test_alc_clip_follows_the_destination_tempo():
    # The whole point of the format: IsSongTempoMaster true would drag the
    # Set to the stem's tempo instead of warping the stem to the Set's.
    clip = _clip_for().find(_SESSION_CLIP)
    assert clip.find("IsSongTempoMaster").attrib["Value"] == "false"
    assert clip.find("IsWarped").attrib["Value"] == "true"
    assert clip.find("MarkersGenerated").attrib["Value"] == "true"


def test_alc_carries_exactly_one_track():
    assert len(_clip_for().findall("LiveSet/Tracks/AudioTrack")) == 1


def test_alc_warp_markers_encode_the_detected_tempo():
    markers = [(float(m.attrib["SecTime"]), float(m.attrib["BeatTime"]))
               for m in _clip_for().findall(".//WarpMarkers/WarpMarker")]
    (first_sec, first_beat), (last_sec, last_beat) = markers[0], markers[-1]
    assert (last_beat - first_beat) / (last_sec - first_sec) * 60 == pytest.approx(124.0)


def test_stems_of_one_song_warp_identically():
    # The bug this format exists to fix: left to its own analysis Live gave
    # two stems of one song two different tempos, so they drifted apart.
    def markers(name):
        root = _clip_for(name, f"/tmp/{name}.flac")
        return [(m.attrib["SecTime"], m.attrib["BeatTime"])
                for m in root.findall(".//WarpMarkers/WarpMarker")]

    assert markers("drums") == markers("vocals")


def test_alc_pointee_ids_are_unique():
    ids = _pointee_ids(_clip_for())
    assert ids
    assert len(ids) == len(set(ids))


def test_alc_next_pointee_id_exceeds_every_allocated_id():
    root = _clip_for()
    nxt = int(root.find("LiveSet/NextPointeeId").attrib["Value"])
    assert nxt > max(_pointee_ids(root))


def test_alc_sample_reference_carries_both_paths():
    ref = _clip_for(path="/tmp/stems/drums.flac").find(".//SampleRef/FileRef")
    assert ref.find("Path").attrib["Value"].endswith("drums.flac")
    assert ref.find("RelativePath").attrib["Value"] == "drums.flac"


def test_write_alc_is_gzipped_and_reparses(tmp_path):
    target = ableton.write_alc(tmp_path / "drums.alc", "drums",
                               "/tmp/drums.flac", 180.0, 124.0)
    assert ET.fromstring(gzip.open(target).read()).tag == "Ableton"


def test_write_alc_is_reproducible(tmp_path):
    args = ("drums", "/tmp/drums.flac", 180.0, 124.0)
    first = ableton.write_alc(tmp_path / "a.alc", *args).read_bytes()
    second = ableton.write_alc(tmp_path / "b.alc", *args).read_bytes()
    assert first == second


def _asd_with(markers):
    """Fabricate the byte layout validated against Ableton's own files."""
    import struct
    out = b"\x00" * 32
    for seconds, beats in markers:
        out += b"WarpMarker" + b"\x00" * 4 + struct.pack("<dd", seconds, beats)
    return out


def test_read_warp_markers_round_trips(tmp_path):
    path = tmp_path / "s.wav.asd"
    path.write_bytes(_asd_with([(0.0, 0.0), (2.0, 4.0)]))
    assert ableton.read_warp_markers(path) == [(0.0, 0.0), (2.0, 4.0)]


def test_tempo_from_asd_infers_the_warped_tempo(tmp_path):
    path = tmp_path / "s.wav.asd"
    path.write_bytes(_asd_with([(0.0, 0.0), (2.0, 4.0)]))
    assert ableton.tempo_from_asd(path) == pytest.approx(120.0)


def test_unwarped_and_missing_files_yield_nothing(tmp_path):
    empty = tmp_path / "e.wav.asd"
    empty.write_bytes(b"\x00" * 64)
    assert ableton.read_warp_markers(empty) == []
    assert ableton.tempo_from_asd(empty) is None
    assert ableton.read_warp_markers(tmp_path / "missing.asd") == []


def test_asd_writing_is_documented_as_unsupported():
    assert "does not write" in ableton.describe_asd_support()
