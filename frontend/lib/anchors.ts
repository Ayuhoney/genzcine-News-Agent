// Shared anchor (avatar) + language data, used by the floating anchor picker.

export const NOVA_FACE_ID =
  process.env.NEXT_PUBLIC_NOVA_FACE_ID ?? 'b9e5fba3-071a-4e35-896e-211c4d6eaa7b';
export const ARIA_FACE_ID =
  process.env.NEXT_PUBLIC_ARIA_FACE_ID ?? 'afdb6a3e-3939-40aa-92df-01604c23101c';
export const MARK_FACE_ID =
  process.env.NEXT_PUBLIC_MARK_FACE_ID ?? 'dd10cb5a-d31d-4f12-b69f-6db3383c006e';

export interface AnchorOption {
  id: string;
  name: string;
  role: string;
  image: string;
  glowRgba: string;
  slot: 'nova' | 'aria' | 'mark';
  /** Short lines shown in the setup popover (auto-slides). */
  intros: string[];
}

export const ANCHORS: AnchorOption[] = [
  {
    id: NOVA_FACE_ID,
    name: 'NOVA',
    role: 'Lead News Anchor',
    image: '/avatar-nova.png',
    glowRgba: 'rgba(230,57,70,0.35)',
    slot: 'nova',
    intros: [
      "Hi, I'm NOVA — GenzCine's lead AI news anchor. Real headlines, live video, real conversation.",
      'I open with top stories, dig into what you care about, and keep the broadcast tight and clear.',
      'Ask for politics, tech, entertainment, or a quick brief — then go live whenever you are ready.',
    ],
  },
  {
    id: ARIA_FACE_ID,
    name: 'ARIA',
    role: 'International Anchor',
    image: '/avatar-aria.png',
    glowRgba: 'rgba(139,92,246,0.30)',
    slot: 'aria',
    intros: [
      "Hi, I'm ARIA — your international desk. Global headlines, world affairs, and cross-border stories.",
      'I cover geopolitics, markets abroad, culture, and breaking news from every region you follow.',
      'Pick a language, tell me what beat matters to you, and we will go live around the world.',
    ],
  },
  {
    id: MARK_FACE_ID,
    name: 'MARK',
    role: 'Sports & Business Anchor',
    image: '/avatar-mark.png',
    glowRgba: 'rgba(59,130,246,0.35)',
    slot: 'mark',
    intros: [
      "Hi, I'm MARK — sports and business. Scores, markets, deals, and the stories behind the numbers.",
      'From match highlights to stock moves and startup news — I keep it fast, sharp, and on the money.',
      'Ask for cricket, football, markets, or a quick business brief — then hit Go Live.',
    ],
  },
];

// ── Session languages — self-hosted Kokoro supported ─────────────────────────
export const LANGUAGES = [
  { code: 'en-US', label: 'English', sub: 'US Accent', flag: '🇺🇸' },
  { code: 'en-GB', label: 'English', sub: 'British Accent', flag: '🇬🇧' },
  { code: 'es', label: 'Español', sub: 'Spanish', flag: '🇪🇸' },
  { code: 'fr', label: 'Français', sub: 'French', flag: '🇫🇷' },
  { code: 'it', label: 'Italiano', sub: 'Italian', flag: '🇮🇹' },
  { code: 'pt-BR', label: 'Português', sub: 'Brazilian Portuguese', flag: '🇧🇷' },
  { code: 'zh', label: '中文', sub: 'Mandarin Chinese', flag: '🇨🇳' },
];

// Kokoro voice per (language, anchor). Voice id prefix picks the language
// pipeline on the TTS server (af_ → US English, jf_ → Japanese, ...).
export const VOICE_MAP: Record<string, { nova: string; aria: string; mark: string }> = {
  'en-US': { nova: 'af_nova', aria: 'af_bella', mark: 'am_michael' },
  'en-GB': { nova: 'bf_emma', aria: 'bf_isabella', mark: 'bm_george' },
  es: { nova: 'ef_dora', aria: 'ef_dora', mark: 'em_alex' },
  fr: { nova: 'ff_siwis', aria: 'ff_siwis', mark: 'ff_siwis' },
  it: { nova: 'if_sara', aria: 'if_sara', mark: 'im_nicola' },
  'pt-BR': { nova: 'pf_dora', aria: 'pf_dora', mark: 'pm_alex' },
  zh: { nova: 'zf_xiaoxiao', aria: 'zf_xiaoni', mark: 'zm_yunxi' },
};
