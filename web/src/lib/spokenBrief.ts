/**
 * What Second says out loud, built from the contract and nothing else.
 *
 * Pure functions, so a test can hand in a brief and read the sentence back.
 * Every clause is a field read off the payload: a count, a title, a time, a
 * summary, a question. Nothing is summarised by guessing, nothing is ranked by
 * a rule the brief does not already carry, and anything the screen shows that
 * is not listed here is simply not said. The ear takes in far less than the
 * eye, so the day is told in the order Today lists it and stops early.
 *
 * Times are said the way a person reads a clock aloud, "at seven" and "at half
 * past five in the afternoon", from the characters of the string, by the rule
 * `lib/datetime.ts` gives: the hour in the string is the hour the person
 * lives in, and nothing here parses a date.
 */

import { isFixtureAcknowledgement, type FixtureAcknowledgement } from '../api/client'
import type {
  DailyBrief,
  HorizonAsked,
  HorizonQuestion,
  IntakeResult,
  LivingGraph,
  ScheduledBlock,
} from '../types/contract'
import { clockTime, dateKey, longDate } from './datetime'

const NUMBER_WORDS = [
  'zero',
  'one',
  'two',
  'three',
  'four',
  'five',
  'six',
  'seven',
  'eight',
  'nine',
  'ten',
  'eleven',
  'twelve',
]

/**
 * The day, as Second would say it.
 *
 * The date; the blocks, counted, with the first two and their times; what was
 * already done for you; how many tasks are at risk and the nearest; then the
 * one thing that decides whether the day needs you: a decision's question, or
 * "Nothing needs you today." That line closes on a quiet day for the reason
 * the decision closes on a loud one, so the last thing heard is the answer to
 * whether anything is wanted.
 *
 * Quiet means what Today means by it: no notification and no decision.
 */
export function spokenBrief(brief: DailyBrief): string {
  const parts: string[] = [`${longDate(brief.on)}.`]

  parts.push(blocksLine(brief.blocks))

  if (brief.prepared.length === 1) {
    const [action] = brief.prepared
    parts.push(`Already done for you: ${sentence(action.summary)}`)
    if (action.awaiting) parts.push(sentence(action.awaiting))
  } else if (brief.prepared.length > 1) {
    parts.push(`${capital(count(brief.prepared.length))} things are already done for you.`)
    for (const action of brief.prepared) parts.push(sentence(action.summary))
  }

  if (brief.at_risk.length > 0) {
    const nearest = brief.at_risk.reduce((near, risk) => (risk.days_left < near.days_left ? risk : near))
    const left = daysLeft(nearest.days_left)
    parts.push(
      brief.at_risk.length === 1
        ? `One task is at risk: ${bare(nearest.what)}, ${left}.`
        : `${capital(count(brief.at_risk.length))} tasks are at risk. The nearest is ${bare(nearest.what)}, ${left}.`,
    )
  }

  const quiet = !brief.notify && brief.decisions.length === 0
  if (brief.decisions.length === 1) {
    parts.push(`One decision needs you. ${sentence(brief.decisions[0].question)}`)
  } else if (brief.decisions.length > 1) {
    parts.push(
      `${capital(count(brief.decisions.length))} decisions need you. The first: ${sentence(brief.decisions[0].question)}`,
    )
  } else if (quiet) {
    parts.push('Nothing needs you today.')
  }

  return parts.join(' ')
}

/** The question as asked, then "By when?" unless it already asks when. */
export function spokenQuestion(question: HorizonQuestion): string {
  const asked = sentence(question.question)
  return /\bwhen\b/i.test(asked) ? asked : `${asked} By when?`
}

/** What was heard, read back before anything is planned from it. */
export function spokenReadBack(heard: string): string {
  return `I heard: ${sentence(heard)} Shall I plan that?`
}

/**
 * What came back from an answer, told from the fields MemoryScreen's `Outcome`
 * shows and in the same order.
 *
 * `generatedFor` is the sentence a fixture reply was generated from, or null
 * live. A plan made for other words says so first, as the screen does, because
 * a plan read out under a sentence it was not made for is a plan for a
 * different sentence. `today` lets a placement on the brief's own day be said
 * as "today" rather than as a date.
 */
export function spokenAnswerReply(
  reply: IntakeResult | FixtureAcknowledgement,
  said: string,
  generatedFor: string | null,
  today: string,
): string {
  if (isFixtureAcknowledgement(reply)) return reply.line

  const parts: string[] = []
  const { clarifying_questions: askedBack, schedule } = reply

  // Compared without case or the closing full stop, which a recogniser
  // supplies or leaves off at random: they do not make the words different.
  if (generatedFor !== null && comparable(said) !== comparable(generatedFor)) {
    parts.push(`Fixture mode: this plan was generated for “${bare(generatedFor)}”, not for your words.`)
  }

  if (askedBack.length > 0) {
    parts.push(
      schedule
        ? 'I planned what follows, and I also need to ask.'
        : 'I need this before I plan anything, so nothing was placed.',
    )
    for (const asked of askedBack) parts.push(sentence(asked))
  }

  if (schedule) {
    const titles = taskTitles(reply.graph)
    const placed = schedule.placed.map((placement) => {
      const title = titles.get(placement.task_id) ?? 'a task this plan does not name'
      return `${bare(title)} ${onDay(placement.start, today)} at ${spokenTime(placement.start)}`
    })
    if (placed.length === 0) parts.push('Nothing was placed.')
    else if (placed.length === 1) parts.push(`I placed one task: ${placed[0]}.`)
    else parts.push(`I placed ${count(placed.length)} tasks: ${andList(placed)}.`)

    const lost = schedule.deprioritised.length
    if (lost > 0) parts.push(`${capital(count(lost))} ${lost === 1 ? 'task lost its slot' : 'tasks lost their slots'} to make room.`)
    if (generatedFor !== null) parts.push('In fixture mode this plan is not written anywhere.')
  }

  if (!schedule && askedBack.length === 0) {
    parts.push('I returned no plan and no questions, so nothing was placed.')
  }

  if (askedBack.length > 0) parts.push('This question stays open until an answer is planned.')

  return parts.join(' ')
}

/** What came back from a skip, in MemoryScreen's words. */
export function spokenSkipReply(
  reply: HorizonAsked | FixtureAcknowledgement,
  horizon: HorizonQuestion['horizon'],
): string {
  if (isFixtureAcknowledgement(reply)) return reply.line
  return `Skipped. I will ask the ${horizon} question again from ${longDate(reply.next_due)}.`
}

/**
 * `07:00` as "seven", `17:30` as "half past five in the afternoon".
 *
 * A morning hour is said bare, the way a person says their own alarm. From
 * midday on the part of the day is added, so seven in the morning and seven in
 * the evening are never the same two words.
 */
export function spokenTime(iso: string): string {
  const [hh, mm] = clockTime(iso).split(':').map(Number)
  if (Number.isNaN(hh) || Number.isNaN(mm)) return clockTime(iso)
  if (mm === 0 && hh === 12) return 'midday'
  if (mm === 0 && hh === 0) return 'midnight'

  const twelve = (hour: number) => NUMBER_WORDS[hour % 12 === 0 ? 12 : hour % 12]
  const part = (hour: number) =>
    hour >= 18 ? ' in the evening' : hour >= 12 ? ' in the afternoon' : ''

  if (mm === 0) return `${twelve(hh)}${part(hh)}`
  if (mm === 30) return `half past ${twelve(hh)}${part(hh)}`
  if (mm === 15) return `quarter past ${twelve(hh)}${part(hh)}`
  // The part of the day is the one the clock is in now: 11:45 is "quarter to
  // twelve", not "quarter to twelve in the afternoon".
  if (mm === 45) return `quarter to ${twelve(hh + 1)}${part(hh)}`
  return `${twelve(hh)} ${mm < 10 ? `oh ${NUMBER_WORDS[mm]}` : mm}${part(hh)}`
}

// ---------------------------------------------------------------------------

function blocksLine(blocks: ScheduledBlock[]): string {
  if (blocks.length === 0) return 'Nothing is scheduled today.'
  const said = blocks.slice(0, 2).map(blockPhrase)
  if (blocks.length === 1) return `One block today: ${said[0]}.`
  if (blocks.length === 2) return `Two blocks today: ${said[0]}, then ${said[1]}.`
  return `${capital(count(blocks.length))} blocks today, starting with ${said[0]}, then ${said[1]}.`
}

/** "Gym session at seven". A proposal is never booked, so it is not said as one. */
function blockPhrase(block: ScheduledBlock): string {
  const phrase = `${bare(block.title)} at ${spokenTime(block.start)}`
  return block.status === 'proposed' ? `${phrase}, proposed` : phrase
}

function daysLeft(days: number): string {
  if (days < 0) return days === -1 ? 'one day overdue' : `${count(-days)} days overdue`
  if (days === 0) return 'due today'
  if (days === 1) return 'one day left'
  return `${count(days)} days left`
}

function onDay(iso: string, today: string): string {
  return dateKey(iso) === today ? 'today' : `on ${longDate(iso)}`
}

/** Task titles by id, walked from the graph a reply carried, as Record's `taskIndex` does. */
function taskTitles(graph: LivingGraph): Map<string, string> {
  const out = new Map<string, string>()
  for (const goal of graph.goals) {
    for (const route of goal.routes) {
      for (const task of route.tasks) out.set(task.id, task.title)
    }
  }
  return out
}

/** Small counts as words, which an engine says more naturally; larger ones as digits. */
function count(n: number): string {
  return n >= 0 && n < NUMBER_WORDS.length ? NUMBER_WORDS[n] : String(n)
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Ends with a full stop, a question mark or an exclamation, adding a full stop if not. */
function sentence(text: string): string {
  const flat = tidy(text)
  if (!flat) return ''
  return /[.!?…]["”’)]?$/.test(flat) ? flat : `${flat}.`
}

/** Without its closing full stop, for a phrase that continues the sentence. */
function bare(text: string): string {
  return tidy(text).replace(/\.+$/, '')
}

function andList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

function tidy(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function comparable(text: string): string {
  return bare(text).toLowerCase()
}
