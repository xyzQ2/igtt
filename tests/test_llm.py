import base64

from src import llm

IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(b"png").decode()}}


def test_anthropic_gets_the_real_sdk(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert type(llm.client({"provider": "anthropic"})).__name__ == "Anthropic"


def test_openai_shim_translates_text_and_image(mocker, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    post = mocker.patch("src.llm.requests.post")
    post.return_value.json.return_value = {"choices": [{"message": {"content": "{\"a\": 1}"}}]}

    resp = llm.client({"provider": "openai"}).messages.create(
        model="gpt-5-mini", max_tokens=16000,
        messages=[{"role": "user", "content": [IMAGE, {"type": "text", "text": "hi"}]}])

    assert resp.content[0].text == '{"a": 1}'
    body = post.call_args.kwargs["json"]
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert body["max_completion_tokens"] == 16000
    parts = body["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "hi"}


def test_google_shim_sends_image_bytes_and_plain_prompt(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    gclient = mocker.patch("src.llm.genai.Client")
    gclient.return_value.models.generate_content.return_value.text = "ok"

    resp = llm.client({"provider": "google"}).messages.create(
        model="gemini-2.5-flash", max_tokens=100,
        messages=[{"role": "user", "content": [IMAGE, {"type": "text", "text": "hi"}]}])

    assert resp.content[0].text == "ok"
    gclient.assert_called_with(api_key="g")
    contents = gclient.return_value.models.generate_content.call_args.kwargs["contents"]
    assert contents[1] == "hi"
    assert contents[0].inline_data.data == b"png"


def test_google_shim_never_returns_none_text(mocker, monkeypatch):
    """A safety-blocked Gemini reply has text None; callers join .text strings."""
    gclient = mocker.patch("src.llm.genai.Client")
    gclient.return_value.models.generate_content.return_value.text = None
    resp = llm.client({"provider": "google"}).messages.create(
        model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}])
    assert resp.content[0].text == ""
