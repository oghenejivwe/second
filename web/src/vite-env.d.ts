/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `fixtures` develops against checked-in payloads; anything else is live. */
  readonly VITE_SOURCE?: 'fixtures' | 'live'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
