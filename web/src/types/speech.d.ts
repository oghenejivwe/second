/**
 * Ambient Web Speech API types, because TypeScript 5.9.3 does not ship them.
 *
 * `lib.dom.d.ts` declares the three objects that come *out* of a recognition --
 * `SpeechRecognitionResultList`, `SpeechRecognitionResult` and
 * `SpeechRecognitionAlternative` -- and nothing that produces them. So what
 * follows declares only `SpeechRecognition` and its two events, reusing the
 * three the lib already has rather than restating them and colliding.
 *
 * Both constructor names are declared because the API is not Baseline: Chrome
 * and Edge expose the prefixed name (and currently the unprefixed one too),
 * Safari exposes only the prefix, Firefox exposes neither. `useRecorder` picks
 * whichever exists and treats absence as a supported state of the screen, not
 * as a failure.
 *
 * Shapes and error codes taken from MDN, not from memory: SpeechRecognition,
 * SpeechRecognitionEvent and SpeechRecognitionErrorEvent/error. Two of the nine
 * codes below are no longer in the specification -- `bad-grammar` went with the
 * removal of grammars, `phrases-not-supported` belongs to contextual biasing
 * this app does not use -- but a browser may still send them, and a union that
 * omits a code the runtime can produce is a lie about the exhaustiveness of
 * every switch over it.
 */

type SpeechRecognitionErrorCode =
  | 'aborted'
  | 'audio-capture'
  | 'bad-grammar'
  | 'language-not-supported'
  | 'network'
  | 'no-speech'
  | 'not-allowed'
  | 'phrases-not-supported'
  | 'service-not-allowed'

interface SpeechRecognitionEvent extends Event {
  /** Lowest index in `results` that changed. Unused here: the list is rebuilt. */
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultList
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: SpeechRecognitionErrorCode
  /** Free text from the engine. Often empty, so never shown on its own. */
  readonly message: string
}

interface SpeechRecognition extends EventTarget {
  /** Keep listening across pauses instead of returning one result and ending. */
  continuous: boolean
  /** Emit results before they settle, which is the whole point of a live pane. */
  interimResults: boolean
  lang: string
  maxAlternatives: number

  onaudioend: ((this: SpeechRecognition, event: Event) => void) | null
  onaudiostart: ((this: SpeechRecognition, event: Event) => void) | null
  onend: ((this: SpeechRecognition, event: Event) => void) | null
  onerror: ((this: SpeechRecognition, event: SpeechRecognitionErrorEvent) => void) | null
  onnomatch: ((this: SpeechRecognition, event: SpeechRecognitionEvent) => void) | null
  onresult: ((this: SpeechRecognition, event: SpeechRecognitionEvent) => void) | null
  onspeechend: ((this: SpeechRecognition, event: Event) => void) | null
  onspeechstart: ((this: SpeechRecognition, event: Event) => void) | null
  onstart: ((this: SpeechRecognition, event: Event) => void) | null

  start(): void
  /** Finalise what is in flight and end. */
  stop(): void
  /** End now and discard what is in flight. */
  abort(): void
}

declare var SpeechRecognition: {
  prototype: SpeechRecognition
  new (): SpeechRecognition
}

declare var webkitSpeechRecognition: {
  prototype: SpeechRecognition
  new (): SpeechRecognition
}
