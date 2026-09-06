from local_voice_ai.services.spoken_lang import detect_spoken_lang


def test_devanagari_is_hindi() -> None:
    assert detect_spoken_lang("\u092b\u093f\u0930\u094b\u091c\u092a\u0941\u0930 \u0915\u0940 \u0916\u092c\u0930") == "hi"


def test_gurmukhi_is_punjabi() -> None:
    assert detect_spoken_lang("\u0a2b\u0a3c\u0a3f\u0a30\u0a4b\u0a1c\u0a3c\u0a2a\u0a41\u0a30") == "pa"


def test_whisper_hindi_on_latin() -> None:
    assert detect_spoken_lang("Firozpur ki khabar do", "hi") == "hi"


def test_whisper_english_stays_english() -> None:
    assert detect_spoken_lang("Give me Firozpur news", "en") == "en"


def test_latin_without_whisper_does_not_flip() -> None:
    assert detect_spoken_lang("Firozpur news please") is None


def test_whisper_punjabi_written_as_hindi_is_still_pa() -> None:
    # Groq Whisper often labels Punjabi audio as Hindi and writes Devanagari.
    assert (
        detect_spoken_lang(
            "\u0938\u0924\u094d\u0938\u094d\u0930\u093f\u092f\u0915\u093e\u0932 \u092e\u0948\u0902 \u091f\u0940\u0928\u093e \u0939\u093e\u0902 \u092e\u094b\u0939\u093e\u0932\u0940 \u092d\u0940 \u0916\u092c\u0930",
            "Hindi",
        )
        == "pa"
    )


def test_sat_sri_akal_latin_is_punjabi() -> None:
    assert detect_spoken_lang("Sat Sri Akal Tina", "en") == "pa"


def test_plain_hindi_news_stays_hindi() -> None:
    assert detect_spoken_lang("\u092e\u0941\u091d\u0947 \u0926\u093f\u0932\u094d\u0932\u0940 \u0915\u0940 \u0916\u092c\u0930 \u0926\u094b", "Hindi") == "hi"


def test_urdu_script_is_hindi() -> None:
    assert detect_spoken_lang("\u0645\u062c\u06be\u06d2 \u062f\u0644\u06cc \u06a9\u06cc \u0646\u06cc\u0648\u0632 \u0628\u062a\u0627\u0624") == "hi"


def test_urdu_ask_hindi_switches() -> None:
    assert (
        detect_spoken_lang("\u06a9\u06cc\u0627 \u062a\u0645 \u06c1\u0646\u062f\u06cc \u0645\u06cc\u06ba \u0628\u0627\u062a \u06a9\u0631 \u0633\u06a9\u062a\u06cc \u06c1\u0648\u061f")
        == "hi"
    )


def test_urdu_ask_punjabi_switches() -> None:
    assert detect_spoken_lang("\u067e\u0646\u062c\u0627\u0628\u06cc \u0645\u06cc\u06ba \u0628\u0648\u0644\u0648") == "pa"


def test_continue_in_english_switches_back() -> None:
    assert detect_spoken_lang("Continue in English.") == "en"
    assert detect_spoken_lang("Speaking in English continue.") == "en"


def test_english_news_without_whisper_does_not_flip() -> None:
    assert detect_spoken_lang("Tell us about Delhi news.") is None
