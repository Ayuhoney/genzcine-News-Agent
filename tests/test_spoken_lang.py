from local_voice_ai.services.spoken_lang import (
    SARVAM_LANGS,
    detect_spoken_lang,
    is_language_switch_only,
    is_stt_garbage,
    language_bridge,
    tts_lang_for_text,
)


def test_devanagari_is_hindi() -> None:
    assert detect_spoken_lang("\u092b\u093f\u0930\u094b\u091c\u092a\u0941\u0930 \u0915\u0940 \u0916\u092c\u0930") == "hi"


def test_gurmukhi_is_punjabi() -> None:
    assert detect_spoken_lang("\u0a2b\u0a3c\u0a3f\u0a30\u0a4b\u0a1c\u0a3c\u0a2a\u0a41\u0a30") == "pa"


def test_tamil_script_is_tamil() -> None:
    assert detect_spoken_lang("\u0b9a\u0bc6\u0ba9\u0bcd\u0ba9\u0bc8 \u0b9a\u0bc6\u0baf\u0bcd\u0ba4\u0bbf\u0b95\u0bb3\u0bcd") == "ta"


def test_bengali_script_is_bengali() -> None:
    assert detect_spoken_lang("\u0986\u099c\u0995\u09c7\u09b0 \u0996\u09ac\u09b0") == "bn"


def test_whisper_hindi_on_latin() -> None:
    assert detect_spoken_lang("Firozpur ki khabar do", "hi") == "hi"


def test_whisper_english_stays_english() -> None:
    assert detect_spoken_lang("Give me Firozpur news", "en") == "en"


def test_latin_without_whisper_does_not_flip() -> None:
    assert detect_spoken_lang("Firozpur news please") is None


def test_whisper_punjabi_written_as_hindi_is_still_pa() -> None:
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


def test_punjab_place_is_not_punjabi_language() -> None:
    assert detect_spoken_lang("Punjab") is None
    assert detect_spoken_lang("All of these are Punjabi.") is None
    assert detect_spoken_lang("If the speaker is Punjabi, transcribe in Devanagari.") is None


def test_whisper_prompt_leak_is_garbage() -> None:
    leak = "If the speaker is Punjabi, transcribe in Ddevanagari. Sat Sri Akal is always Punjabi."
    assert is_stt_garbage(leak)
    assert detect_spoken_lang(leak) is None
    assert is_stt_garbage("Thank you for watching!")
    assert detect_spoken_lang("Thank you for watching!") is None
    assert not is_stt_garbage("Sat Sri Akal Tina")
    assert detect_spoken_lang("Sat Sri Akal Tina") == "pa"


def test_explicit_speak_punjabi_still_switches() -> None:
    assert detect_spoken_lang("Speak Punjabi") == "pa"
    assert detect_spoken_lang("punjabi mein bolo") == "pa"


def test_speak_english_with_me_switches_back() -> None:
    assert detect_spoken_lang("No, can you still speak English with me?") == "en"


def test_speak_tamil_switches() -> None:
    assert detect_spoken_lang("Speak Tamil please") == "ta"
    assert detect_spoken_lang("tamil mein bolo") == "ta"


def test_hinglish_news_is_hindi() -> None:
    assert detect_spoken_lang("Mujhe Aashika Nepal ka news batao.") == "hi"


def test_switch_only_phrases() -> None:
    assert is_language_switch_only("No, can you still speak English with me?")
    assert is_language_switch_only("Speak Tamil please")
    assert is_language_switch_only("\u062a\u0645 \u0645\u062c\u06be\u06d2 \u06c1\u0646\u062f\u06cc \u0645\u06cc\u06ba \u0633\u0646 \u0633\u06a9\u062a\u06cc \u06c1\u0648")
    assert not is_language_switch_only("Mujhe Aashika Nepal ka news batao.")
    assert not is_language_switch_only("\u092e\u0941\u091d\u0947 \u0926\u093f\u0932\u094d\u0932\u0940 \u0915\u0940 \u0916\u092c\u0930 \u0926\u094b")


def test_language_bridge_covers_all_sarvam_langs() -> None:
    for code in SARVAM_LANGS:
        assert language_bridge(code), code
    assert "\u0939\u093f\u0902\u0926\u0940" in language_bridge("hi")
    assert "\u0a2a\u0a70\u0a1c\u0a3e\u0a2c\u0a40" in language_bridge("pa")
    assert "English" in language_bridge("en")


def test_thinking_filler_covers_all_sarvam_langs() -> None:
    from local_voice_ai.services.spoken_lang import thinking_filler

    for code in SARVAM_LANGS:
        assert thinking_filler(code), code
    assert thinking_filler("hi").startswith("\u090f\u0915")
    assert "second" in thinking_filler("en").lower() or "\u2026" in thinking_filler("en")


def test_tts_lang_script_is_strict() -> None:
    assert tts_lang_for_text("\u0928\u092e\u0938\u094d\u0924\u0947", "en") == "hi"
    assert tts_lang_for_text("\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32", "en") == "pa"
    assert tts_lang_for_text("You're watching GenzCine.", "en") == "en"
    assert tts_lang_for_text("TINA", "hi") == "hi"
    assert tts_lang_for_text("Hello", "ta") == "ta"


def test_intro_segments_use_native_scripts() -> None:
    from local_voice_ai.agent import _tv_open_segments

    segs = _tv_open_segments("TINA", None)
    assert [c for c, _ in segs] == ["hi", "pa", "en"]
    assert tts_lang_for_text(segs[0][1], "en") == "hi"
    assert tts_lang_for_text(segs[1][1], "en") == "pa"
    assert tts_lang_for_text(segs[2][1], "en") == "en"
    assert "\u0928\u092e\u0938\u094d\u0924\u0947" in segs[0][1]
    assert "\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32" in segs[1][1]
    named = _tv_open_segments("TINA", "Ayush")
    assert named[0][1] == segs[0][1] and named[1][1] == segs[1][1]
    assert "Ayush" in named[2][1]


def test_whisper_label_alone_needs_enough_words() -> None:
    assert detect_spoken_lang("Mohali", "en", current="hi") is None
    assert detect_spoken_lang("Delhi news", "en-US", current="hi") is None
    assert detect_spoken_lang("What is happening in Delhi today", "en", current="hi") == "en"
    assert detect_spoken_lang("Mohali", "hi", current="hi") == "hi"
    assert detect_spoken_lang("\u092e\u094b\u0939\u093e\u0932\u0940", "en", current="en") == "hi"
    assert detect_spoken_lang("in english", "hi", current="hi") == "en"


def test_sentence_splitter_streams_per_sentence() -> None:
    from local_voice_ai.services.sarvam_tts import split_complete_sentences

    done, rest = split_complete_sentences("Our top story. Punjab CM announces relief. Officials say")
    assert done == ["Our top story.", "Punjab CM announces relief."]
    assert rest == "Officials say"
    done, rest = split_complete_sentences(
        "\u0905\u0917\u0932\u0940 \u0916\u092c\u0930\u0964 Punjab CM announces flood relief. More soon"
    )
    assert done == ["\u0905\u0917\u0932\u0940 \u0916\u092c\u0930\u0964 Punjab CM announces flood relief."]
    assert rest == "More soon"
    done, rest = split_complete_sentences("Rs. 1.5 crore was released by Dr. Singh today. Next")
    assert done == ["Rs. 1.5 crore was released by Dr. Singh today."]
    assert rest == "Next"
    assert split_complete_sentences("no boundary yet") == ([], "no boundary yet")
