/**
 * The sentence Second says after a request is sent: what it heard and where it put it.
 *
 * Built from two things only, so it never claims more than happened: the words
 * the person used to say where they wanted it ("calendar", "this week"), and
 * what the intake result carries (questions back, blocks placed). A calendar is
 * only named when a block really holds a calendar event, or in fixture mode,
 * where the whole screen is already labelled as example data.
 */
import { USING_FIXTURES } from '../api/client'
import type { IntakeResult } from '../types/contract'

const DESTINATIONS: [RegExp, string][] = [
  [/\bcalendar\b/i, 'your calendar'],
  [/\bschedule\b/i, 'your schedule'],
  [/\b(this|next) week\b|\bweekly\b/i, "this week's goals"],
  [/\b(this|next) month\b|\bmonthly\b/i, "this month's goals"],
  [/\b(this|next) year\b|\byearly\b/i, "this year's goals"],
  [/\blong[- ]term\b|\blifetime\b/i, 'your long-term goals'],
]

const LEAD = /^(ok(ay)?|so|please|hey second|second)[,\s]+/i
const ASK = /^(can you|could you|would you|i want to|i'd like to|i would like to|help me)\s+/i
const VERB = /^(add|put|schedule|set|plan|create|remind me to|remind me)\s+/i
const TAIL = /\s+(to|in|on|into)\s+(my|the)\s+(calendar|schedule|weekly goals|monthly goals|goals|plan)\b.*$/i

export function destination(transcript: string, result: IntakeResult): string {
  for (const [pattern, place] of DESTINATIONS) {
    if (!pattern.test(transcript)) continue
    const booked = result.schedule?.placed.some((block) => block.calendar_event_id !== null)
    if (place === 'your calendar' && !booked && !USING_FIXTURES) return 'your schedule'
    return place
  }
  return 'your plan'
}

/** The request itself, trimmed to a short title: "Finish the pitch deck by Friday". */
export function requestTitle(transcript: string): string {
  let text = transcript.trim().split(/[.!?\n]/)[0] ?? ''
  text = text.replace(LEAD, '').replace(ASK, '').replace(VERB, '').replace(TAIL, '').trim()
  const short = text.split(/\s+/).filter(Boolean).slice(0, 10).join(' ')
  return short ? short.charAt(0).toUpperCase() + short.slice(1) : ''
}

export function confirmation(transcript: string, result: IntakeResult): string {
  if (result.clarifying_questions.length > 0) {
    return `I heard you, but I need one thing before I plan it: ${result.clarifying_questions[0]}`
  }
  const title = requestTitle(transcript)
  let line = `Done. I added ${title ? `“${title}”` : 'that'} to ${destination(transcript, result)}.`

  const placed = [...(result.schedule?.placed ?? [])].sort((a, b) => a.start.localeCompare(b.start))
  if (placed.length > 0) {
    const when = new Date(placed[0].start)
    const day = when.toLocaleDateString('en-GB', { weekday: 'long' })
    const time = when.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    const count = placed.length === 1 ? 'One block is' : `${placed.length} blocks are`
    line += ` ${count} in your schedule, the first on ${day} at ${time}.`
  }
  return line
}
