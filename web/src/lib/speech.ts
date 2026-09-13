/**
 * Second's voice: `speechSynthesis`, one sentence at a time, and a promise that
 * cannot reject.
 *
 * **Every call resolves.** It resolves when the last sentence has been spoken,
 * when its signal aborts, when the browser has no synthesis at all, and when
 * the engine reports an error. A caller writes `await speak(line)` and then
 * checks its own signal; nothing that goes wrong with a voice is worth a
 * `catch` in a conversation, because the words are on screen as a caption
 * whether they were heard or not.
 *
 * **Long text is split into sentences and queued.** Chrome stops an utterance
 * after roughly fifteen seconds and does not always fire `end` when it does, so
 * a brief read as one utterance goes silent mid-sentence and the promise never
 * settles. A sentence is short enough to finish, and a watchdog per sentence
 * covers the `end` that still sometimes goes missing.
 *
 * **One voice at a time.** A new call ends the one before it, because two
 * sentences from two places interleaving in one voice is worse than either.
 * Aborting a signal cancels the engine only while that call is the one
 * speaking, so a panel closing on one screen cannot silence another.
 *
 * `window.speechSynthesis` is read at call time, never at module load, so a
 * test can stub it after importing this file.
 */

export interface SpeakOptions {
  /** Aborting ends this call's speech and resolves its promise. */
  signal?: AbortSignal
  /** 1 is the engine's normal pace. Kept near it: slower reads as condescending. */
  rate?: number
}

/** Longest piece handed to the engine in one utterance. Well inside Chrome's cut-off. */
const MAX_CHUNK = 220

/** How long to wait for Chrome's voice list, which arrives after the first call. */
const VOICES_WAIT_MS = 800

/**
 * Chrome can drop an utterance handed over immediately after `cancel`. A beat
 * between the two costs nothing a listener notices.
 */
const AFTER_CANCEL_MS = 60

/** The call currently speaking, so the next one can end it. */
let active: { finish: () => void } | null = null

/**
 * Utterances the engine is still holding. Chrome garbage-collects an utterance
 * nothing in script references, and a collected utterance never fires `end`.
 */
const holding = new Set<SpeechSynthesisUtterance>()

export function isSpeechSupported(): boolean {
  return synthesis() !== null
}

/** End whatever Second is saying, from anywhere. */
export function cancelSpeech(): void {
  const current = active
  active = null
  current?.finish()
  synthesis()?.cancel()
}

export function speak(text: string, options: SpeakOptions = {}): Promise<void> {
  const synth = synthesis()
  const { signal, rate = 1 } = options
  const pieces = sentences(text)
  if (!synth || pieces.length === 0 || signal?.aborted) return Promise.resolve()

  return new Promise<void>((resolve) => {
    let done = false
    let watchdog: number | null = null

    const self = {
      finish: () => {
        if (done) return
        done = true
        if (watchdog !== null) window.clearTimeout(watchdog)
        signal?.removeEventListener('abort', onAbort)
        if (active === self) active = null
        resolve()
      },
    }

    function onAbort() {
      // Only the call that is speaking may silence the engine.
      const speaking = active === self
      self.finish()
      if (speaking) synth?.cancel()
    }

    const previous = active
    active = self
    previous?.finish()
    signal?.addEventListener('abort', onAbort, { once: true })

    void (async () => {
      if (synth.speaking || synth.pending) {
        synth.cancel()
        await delay(AFTER_CANCEL_MS)
      }
      const voice = pickVoice(await voices(synth))
      if (done) return
      // A tab that was backgrounded can leave the engine paused, and a paused
      // engine queues utterances without saying any of them.
      if (synth.paused) synth.resume()

      for (const piece of pieces) {
        if (done) return
        await say(synth, piece, voice, rate, () => done, (id) => (watchdog = id))
      }
      self.finish()
    })()
  })
}

// ---------------------------------------------------------------------------

function synthesis(): SpeechSynthesis | null {
  if (typeof window === 'undefined') return null
  if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') return null
  return window.speechSynthesis ?? null
}

/** One utterance, resolved on `end`, on `error`, or when the watchdog finds the engine silent. */
function say(
  synth: SpeechSynthesis,
  text: string,
  voice: SpeechSynthesisVoice | null,
  rate: number,
  cancelled: () => boolean,
  setWatchdog: (id: number | null) => void,
): Promise<void> {
  return new Promise<void>((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text)
    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    } else {
      utterance.lang = 'en-GB'
    }
    utterance.rate = rate
    holding.add(utterance)

    let settled = false
    const settle = () => {
      if (settled) return
      settled = true
      setWatchdog(null)
      holding.delete(utterance)
      resolve()
    }
    utterance.onend = settle
    // `interrupted` and `canceled` arrive here on every cancel. Neither is a
    // failure worth reporting, and the rest would not be fixed by retrying.
    utterance.onerror = settle

    // A generous allowance at normal pace: about fifteen characters a second
    // is spoken, so this is several times that. When it runs out, the engine
    // is asked whether it is still talking before the sentence is given up on.
    const allowance = Math.max(4000, (text.length * 200) / rate)
    const check = () => {
      if (settled) return
      if (!cancelled() && (synth.speaking || synth.pending)) {
        setWatchdog(window.setTimeout(check, 1000))
        return
      }
      settle()
    }
    setWatchdog(window.setTimeout(check, allowance))

    synth.speak(utterance)
  })
}

/** The voice list, waiting briefly for Chrome, which fills it in after the first call. */
function voices(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice[]> {
  const now = synth.getVoices()
  if (now.length > 0) return Promise.resolve(now)

  return new Promise((resolve) => {
    const finish = () => {
      window.clearTimeout(timer)
      synth.removeEventListener('voiceschanged', finish)
      resolve(synth.getVoices())
    }
    const timer = window.setTimeout(finish, VOICES_WAIT_MS)
    synth.addEventListener('voiceschanged', finish)
  })
}

/**
 * British English, then American, then any English; a local voice before a
 * network one at each step.
 *
 * Local first because a network voice starts late and, in Chrome, is the one
 * that cuts off long utterances. Null leaves the choice to the engine, with the
 * utterance's language set so it still picks an English voice where it has one.
 */
export function pickVoice(list: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const lang = (voice: SpeechSynthesisVoice) => voice.lang.replace('_', '-').toLowerCase()
  const tiers: ((voice: SpeechSynthesisVoice) => boolean)[] = [
    (voice) => lang(voice) === 'en-gb',
    (voice) => lang(voice) === 'en-us',
    (voice) => lang(voice).startsWith('en'),
  ]
  for (const tier of tiers) {
    const matching = list.filter(tier)
    const local = matching.find((voice) => voice.localService)
    if (local) return local
    if (matching.length > 0) return matching[0]
  }
  return null
}

/**
 * The text as pieces the engine will finish: one per sentence, and a sentence
 * longer than `MAX_CHUNK` broken again at a comma or a space.
 */
export function sentences(text: string): string[] {
  const flat = text.replace(/\s+/g, ' ').trim()
  if (!flat) return []

  const out: string[] = []
  for (const sentence of flat.split(/(?<=[.!?…])\s+/)) {
    let rest = sentence
    while (rest.length > MAX_CHUNK) {
      const head = rest.slice(0, MAX_CHUNK)
      const cut = Math.max(head.lastIndexOf(', '), head.lastIndexOf('; '))
      const at = cut > MAX_CHUNK / 3 ? cut + 1 : head.lastIndexOf(' ')
      const end = at > 0 ? at : MAX_CHUNK
      out.push(rest.slice(0, end).trim())
      rest = rest.slice(end).trim()
    }
    if (rest) out.push(rest)
  }
  return out
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}
