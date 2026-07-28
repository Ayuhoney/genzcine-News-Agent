export interface AppConfig {
  pageTitle: string;
  pageDescription: string;
  companyName: string;

  supportsChatInput: boolean;
  supportsVideoInput: boolean;
  supportsScreenShare: boolean;
  isPreConnectBufferEnabled: boolean;

  logo: string;
  startButtonText: string;
  accent?: string;
  logoDark?: string;
  accentDark?: string;

  // for LiveKit Cloud Sandbox
  sandboxId?: string;
  agentName?: string;
}

export const APP_CONFIG_DEFAULTS: AppConfig = {
  companyName: 'GenzCine',
  pageTitle: 'NOVA · GenzCine AI News Anchor',
  pageDescription: 'Your AI-powered live news anchor by GenzCine',

  supportsChatInput: false,
  supportsVideoInput: false,
  supportsScreenShare: false,
  isPreConnectBufferEnabled: true,

  logo: '',
  accent: '#E63946',
  logoDark: '',
  accentDark: '#E63946',
  startButtonText: 'Go Live',

  // for LiveKit Cloud Sandbox
  sandboxId: undefined,
  agentName: undefined,
};
