import json

import pytest

from src import analyze


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


VALID = {
    "hook": "POV setup", "hook_type": "relatability", "payoff": "absurd reveal",
    "emotional_driver": "recognition", "humor_mechanism": "escalation",
    "social_driver": "tag a coworker", "comment_driver": "share your worst shift",
    "rewatch_driver": "fast cut loop", "visual_structure": "single take",
    "caption_role": "sets the premise", "audience": "restaurant staff",
    "timing": "none",
    "why_it_overperformed": ["specific", "recognisable", "short"],
    "reusable_pattern": "Insider frustration + recognisable setup + outsized reaction",
    "scores": {"hook": 92, "shareability": 88, "originality": 70,
               "relatability": 95, "rewatchability": 80, "cultural_relevance": 60},
    "ai_virality_score": 89,
}


def test_load_prompt_reads_file():
    text = analyze.load_prompt("analyze_text")
    assert "REUSABLE PATTERN" in text


def test_extract_json_plain():
    assert analyze.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert analyze.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_returns_none_on_garbage():
    assert analyze.extract_json("I'm sorry, I can't do that") is None


def test_analyze_text_returns_parsed_json(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    out = analyze.analyze_text(client, {"shortcode": "A", "caption": "c"},
                               {"name": "DTW", "voice": "v"}, "claude-sonnet-5")
    assert out["ai_virality_score"] == 89
    assert out["reusable_pattern"].startswith("Insider frustration")


def test_analyze_text_retries_once_then_gives_up(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("not json at all")
    out = analyze.analyze_text(client, {"shortcode": "A"}, {"name": "D", "voice": "v"},
                               "claude-sonnet-5")
    assert out is None
    assert client.messages.create.call_count == 2, "one retry, then give up"


def test_analyze_text_rejects_response_missing_required_keys(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response('{"hook": "only this"}')
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None


def test_analyze_text_survives_api_exception(mocker):
    client = mocker.Mock()
    client.messages.create.side_effect = Exception("rate limited")
    assert analyze.analyze_text(client, {"shortcode": "A"},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5") is None


def test_analyze_text_rejects_response_missing_humor_mechanism(mocker):
    incomplete = {k: v for k, v in VALID.items() if k != "humor_mechanism"}
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(incomplete))
    out = analyze.analyze_text(client, {"shortcode": "A"}, {"name": "D", "voice": "v"},
                               "claude-sonnet-5")
    assert out is None
    assert client.messages.create.call_count == 2


VALID_BLUEPRINT = {
    "core_concept": "server rates guest wine orders",
    "target_audience": "restaurant workers",
    "hook_analysis": {"visual_elements": "close on wine list",
                      "audio_elements": "'you ordered WHAT'",
                      "psychological_trigger": "in-group recognition",
                      "hook_formula": "Show [X] + State '[Y]' + Promise '[Z]'"},
    "content_structure": {"opening": "cold open", "development": "three examples",
                          "climax_payoff": "worst order", "call_to_action": "comment yours"},
    "visual_style": {"layout": "single shot", "text_overlays": "captions bottom third",
                     "camera_work": "handheld push-in", "ui_style": "none",
                     "speaker_framing": "medium close", "music": "none"},
    "recreation_framework": {"universal_elements": ["insider POV"],
                             "customizable_elements": ["the niche"],
                             "common_variations": ["ranked list version"]},
}


def test_analyze_video_downloads_and_parses(mocker):
    mock_get = mocker.patch("src.analyze.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = b"fake mp4 bytes"

    mock_client_cls = mocker.patch("src.analyze.genai.Client")
    client = mock_client_cls.return_value
    client.models.generate_content.return_value.text = json.dumps(VALID_BLUEPRINT)

    out = analyze.analyze_video("key", "https://scontent.cdninstagram.com/reel.mp4", "models/gemini-2.5-flash")
    assert out["recreation_framework"]["universal_elements"] == ["insider POV"]
    mock_get.assert_called_once()


def test_analyze_video_returns_none_without_url():
    assert analyze.analyze_video("key", None, "models/gemini-2.5-flash") is None


def test_analyze_video_survives_download_failure(mocker):
    mocker.patch("src.analyze.requests.get", side_effect=Exception("404"))
    mocker.patch("src.analyze.genai.Client")
    assert analyze.analyze_video("key", "https://scontent.cdninstagram.com/x.mp4",
                                 "models/gemini-2.5-flash") is None


def test_analyze_video_refuses_untrusted_host(mocker):
    """A video_url pointing anywhere but Instagram's CDN must never be fetched —
    it could target an internal address on the Actions runner."""
    mock_get = mocker.patch("src.analyze.requests.get")
    assert analyze.analyze_video("key", "https://evil.example.com/x.mp4",
                                 "models/gemini-2.5-flash") is None
    mock_get.assert_not_called()


def test_analyze_video_refuses_non_https_scheme(mocker):
    mock_get = mocker.patch("src.analyze.requests.get")
    assert analyze.analyze_video("key", "http://scontent.cdninstagram.com/x.mp4",
                                 "models/gemini-2.5-flash") is None
    mock_get.assert_not_called()


def test_analyze_video_rejects_incomplete_blueprint(mocker):
    mock_get = mocker.patch("src.analyze.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = b"bytes"
    mock_client_cls = mocker.patch("src.analyze.genai.Client")
    mock_client_cls.return_value.models.generate_content.return_value.text = (
        '{"core_concept": "only this"}'
    )
    assert analyze.analyze_video("key", "https://scontent.cdninstagram.com/x.mp4",
                                 "models/gemini-2.5-flash") is None


THUMB = "https://scontent.cdninstagram.com/v/t51/cover.jpg"


def test_analyze_text_sends_the_cover_image(mocker):
    get = mocker.patch("src.analyze.requests.get")
    get.return_value.headers = {"Content-Type": "image/jpeg"}
    get.return_value.content = b"\xff\xd8jpeg"
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    assert analyze.analyze_text(client, {"shortcode": "A", "thumbnail_url": THUMB},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5")
    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "text"


def test_analyze_text_falls_back_to_text_when_image_fails(mocker):
    mocker.patch("src.analyze.requests.get", side_effect=Exception("403"))
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    assert analyze.analyze_text(client, {"shortcode": "A", "thumbnail_url": THUMB},
                                {"name": "D", "voice": "v"}, "claude-sonnet-5")
    assert isinstance(client.messages.create.call_args.kwargs["messages"][0]["content"],
                      str)


def test_analyze_text_never_fetches_untrusted_thumbnail_hosts(mocker):
    get = mocker.patch("src.analyze.requests.get")
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(VALID))
    analyze.analyze_text(client, {"shortcode": "A",
                                  "thumbnail_url": "http://169.254.169.254/x.jpg"},
                         {"name": "D", "voice": "v"}, "claude-sonnet-5")
    get.assert_not_called()
