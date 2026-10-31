/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_USE_SAMPLE?: string;
  readonly VITE_SHOW_METAL_PRICES?: string;
  readonly VITE_SAMPLE_ACCURACY?: string;
  readonly VITE_AUTH_ENABLED?: string;
  readonly VITE_REGION?: string;
  readonly VITE_USER_POOL_ID?: string;
  readonly VITE_USER_POOL_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
