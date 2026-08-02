import centrifugue_config as cc


def test_successful_choice_returns_path():
    result = cc.parse_folder_choice(0, "/Users/me/Music/Centrifugue/\n", "")
    assert result["success"] is True
    assert result["output_dir"] == "/Users/me/Music/Centrifugue"


def test_trailing_slash_is_stripped():
    # `POSIX path of` always appends a slash for folders
    assert cc.parse_folder_choice(0, "/tmp/x/\n", "")["output_dir"] == "/tmp/x"


def test_root_keeps_its_single_slash():
    assert cc.parse_folder_choice(0, "/\n", "")["output_dir"] == "/"


def test_user_cancel_is_reported_as_cancelled_not_an_error():
    result = cc.parse_folder_choice(1, "", "execution error: User canceled. (-128)")
    assert result["success"] is False
    assert result["cancelled"] is True


def test_cancel_detected_by_error_code_alone():
    result = cc.parse_folder_choice(1, "", "execution error: (-128)")
    assert result["cancelled"] is True


def test_empty_stdout_with_zero_exit_counts_as_cancel():
    result = cc.parse_folder_choice(0, "   \n", "")
    assert result["success"] is False
    assert result["cancelled"] is True


def test_real_failure_surfaces_the_message():
    result = cc.parse_folder_choice(1, "", "osascript: command not found")
    assert result["success"] is False
    assert result.get("cancelled") is not True
    assert "command not found" in result["error"]


def test_failure_without_stderr_still_has_an_error():
    result = cc.parse_folder_choice(1, "", "")
    assert result["success"] is False
    assert result["error"]
