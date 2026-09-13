/**
 * What to keep in mind today, where Second read each thing, and the question it is due to ask.
 *
 * **Grouped by what each item asks of you, for a five-second read.** What happens
 * today comes first, because it has a time. Then what is waiting on you -- a
 * draft to send, a reply you owe -- because only you can clear it. Then
 * deadlines, nearest first. Then what you told Second, and last the standing
 * rules, which change least. `GROUP` maps every `MemoryItem.kind` to one of
 * these and is typed as a `Record`, so a kind added to the contract fails the
 * build here instead of vanishing from the screen.
 *
 * **Every item prints its source beside its evidence**, in mono, because every
 * one of them is a quote: the calendar entry, the email, the graph fact.
 *
 * **Every source is listed, whether or not it said anything.** A calendar with
 * nothing in it and a calendar that could not be read both produce no items,
 * and only the first means the day is clear. So the strip carries each source's
 * own sentence, and a source that could not be read is named again above the
 * items, where an empty group would otherwise be taken as an answer.
 *
 * **The questions sit above the items.** They are the one thing here that wants
 * something back, so they get the treatment a decision gets on Today. Answering
 * or skipping settles that asking of a question in the store, for the session,
 * and the reply replaces the text box. An answer Second asked back about is the
 * exception: the server records nothing for it and the question is still due,
 * so the box stays open under the questions it asked.
 *
 * **Fixture mode shows the generated replies where there are any.** The week
 * question's answer and skip were generated from the real code, so they render
 * as a live reply would. Nothing was generated for the month question, and its
 * reply says so. A question anchored to a goal paused or retired this session is
 * taken off with a sentence saying why, because the checked-in memory cannot be
 * read again the way live memory is.
 */

import { useEffect, useState } from 'react'

import { Problem } from '../components/Problem'
import { Section } from '../components/Section'
import {
  errorLine,
  FIXTURE_WEEK_ANSWER,
  isFixtureAcknowledgement,
  USING_FIXTURES,
  type QuestionHorizon,
} from '../api/client'
import { bySlot, clockTime, longDate, shortDate } from '../lib/datetime'
import { andList, whyWithdrawn, withdrawQuestions } from '../lib/withdrawn'
import { questionKey, useSecond, type SettledQuestion } from '../store/useSecond'
import type {
  Goal,
  HorizonQuestion,
  IntakeResult,
  MemoryItem,
  MemorySourceStatus,
} from '../types/contract'
import { Planned } from './Record'
import styles from './MemoryScreen.module.css'

type GroupId = 'today' | 'waiting' | 'deadlines' | 'told' | 'rules'

const GROUP: Record<MemoryItem['kind'], GroupId> = {
  event: 'today',
  waiting_on_you: 'waiting',
  reminder: 'waiting',
  deadline: 'deadlines',
  told_second: 'told',
  constraint: 'rules',
}

const GROUPS: { id: GroupId; label: string }[] = [
  { id: 'today', label: 'On today' },
  { id: 'waiting', label: 'Waiting on you' },
  { id: 'deadlines', label: 'Deadlines' },
  { id: 'told', label: 'You told Second' },
  { id: 'rules', label: 'Standing rules' },
]

const HORIZON_NAME: Record<QuestionHorizon, string> = { week: 'This week', month: 'This month' }
const HORIZON_ORDER: Record<QuestionHorizon, number> = { week: 0, month: 1 }

export function MemoryScreen() {
  const memory = useSecond((state) => state.memory)
  const graph = useSecond((state) => state.graph)
  const error = useSecond((state) => state.errors.memory)
  const loadMemory = useSecond((state) => state.loadMemory)
  const settled = useSecond((state) => state.settled)

  useEffect(() => {
    if (!memory) void loadMemory()
  }, [memory, loadMemory])

  if (error && !memory) {
    return (
      <div className={styles.screen}>
        <Problem what={error} onRetry={() => void loadMemory()} />
      </div>
    )
  }

  if (!memory) {
    return (
      <div className={styles.screen}>
        <p className={styles.waiting}>Reading what to remember.</p>
      </div>
    )
  }

  const unread = memory.sources.filter((source) => !source.connected)
  const calendar = memory.sources.find((source) => source.name === 'calendar')
  const shown = shownQuestions(memory.questions, settled)
  const withdrawn = USING_FIXTURES ? withdrawQuestions(shown, graph) : null
  const questions = withdrawn?.questions ?? shown

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <h1 className={styles.title}>Memory</h1>
        <p className={styles.what}>
          What to keep in mind on {longDate(memory.on)}, and where Second read each thing.
        </p>
      </header>

      <Sources sources={memory.sources} />

      {error && <Problem what={error} onRetry={() => void loadMemory()} />}

      {unread.length > 0 && (
        <ul className={styles.unread}>
          {unread.map((source) => (
            <li key={source.name} className={styles.unreadItem}>
              <p className={styles.unreadWhat}>
                {source.name} could not be read, so nothing from it is listed below.
              </p>
              <p className="evidence">{source.reason}</p>
            </li>
          ))}
        </ul>
      )}

      <div className={styles.body}>
        {withdrawn && withdrawn.removed.length > 0 && (
          <p className={styles.withdrawn}>{withdrawnLine(withdrawn.removed, withdrawn.goals)}</p>
        )}

        {questions.length > 0 && (
          <Section
            label={questions.length === 1 ? 'One question' : 'Questions'}
            count={questions.length > 1 ? questions.length : undefined}
          >
            <ul className={styles.asks}>
              {questions.map((question) => (
                <Ask
                  key={questionKey(question)}
                  question={question}
                  settled={settled[questionKey(question)]}
                />
              ))}
            </ul>
          </Section>
        )}

        {GROUPS.map((group) => {
          const items = memory.items
            .filter((item) => GROUP[item.kind] === group.id)
            .sort(order(group.id))

          // "On today" is always shown, because an empty one is the question a
          // person opens this screen to answer. The others only when they hold
          // something; a source that could not feed them is named above.
          if (items.length === 0 && group.id !== 'today') return null

          return (
            <Section key={group.id} label={group.label} count={items.length}>
              {items.length === 0 ? (
                <EmptyToday calendar={calendar} />
              ) : (
                <ul className={styles.items}>
                  {items.map((item, index) => (
                    <Item key={`${item.source}:${item.kind}:${index}`} item={item} />
                  ))}
                </ul>
              )}
            </Section>
          )
        })}
      </div>
    </div>
  )
}

function Sources({ sources }: { sources: MemorySourceStatus[] }) {
  return (
    <ul className={styles.sources} aria-label="Sources">
      {sources.map((source) => (
        <li key={source.name} className={styles.source} data-connected={source.connected}>
          <p className={styles.sourceHead}>
            <span className={styles.sourceName}>{source.name}</span>
            <span className={`tabular ${styles.sourceState}`}>
              {source.connected
                ? `connected · ${source.items} ${source.items === 1 ? 'item' : 'items'}`
                : 'not connected'}
            </span>
          </p>
          <p className={styles.sourceReason}>{source.reason}</p>
        </li>
      ))}
    </ul>
  )
}

function Item({ item }: { item: MemoryItem }) {
  // The time for an event and the date for a deadline, formatted off the
  // string. The day count is already in the evidence, computed in Python.
  const when = item.at ? clockTime(item.at) : item.due ? shortDate(item.due) : null

  return (
    <li className={styles.item}>
      <p className={styles.itemWhat}>{item.what}</p>
      {when && <span className={`tabular ${styles.when}`}>{when}</span>}
      <p className={`evidence ${styles.quote}`}>
        <span className={styles.from}>{item.source}</span> · {item.evidence}
      </p>
    </li>
  )
}

/** An empty "On today" means something only when the calendar was read. */
function EmptyToday({ calendar }: { calendar: MemorySourceStatus | undefined }) {
  if (!calendar) {
    return <p className={styles.nothing}>No calendar source is registered, so nothing timed is listed.</p>
  }
  if (!calendar.connected) {
    return (
      <p className={styles.nothing}>
        The calendar could not be read, so an empty list here says nothing about the day.
      </p>
    )
  }
  return (
    <p className="evidence">
      <span className={styles.from}>calendar</span> · {calendar.reason}
    </p>
  )
}

function order(group: GroupId): (a: MemoryItem, b: MemoryItem) => number {
  if (group === 'today') return (a, b) => bySlot(a.at ?? '', b.at ?? '')
  if (group === 'deadlines') return (a, b) => bySlot(a.due ?? '', b.due ?? '')
  return () => 0
}

/**
 * The due questions, plus any settled this session that are no longer due.
 *
 * Live, answering writes `asked_on`, so the next read of memory drops the
 * question. The reply is still worth seeing, so the settled one stays on screen.
 */
function shownQuestions(
  due: HorizonQuestion[],
  settled: Record<string, SettledQuestion>,
): HorizonQuestion[] {
  const horizons = new Set(due.map((question) => question.horizon))
  const gone = Object.values(settled)
    .filter((entry) => !horizons.has(entry.question.horizon))
    .map((entry) => entry.question)

  return [...due, ...gone].sort((a, b) => HORIZON_ORDER[a.horizon] - HORIZON_ORDER[b.horizon])
}

/** `The week question was taken off because “X” is paused.` */
function withdrawnLine(removed: HorizonQuestion[], goals: Goal[]): string {
  const horizons = andList(removed.map((question) => question.horizon))
  const noun = removed.length === 1 ? 'question was' : 'questions were'
  return `The ${horizons} ${noun} taken off because ${whyWithdrawn(goals)}.`
}

/**
 * An answer Second asked back about has not settled anything.
 *
 * The server records `asked_on` only when the answer was planned, so after
 * clarifying questions the question is still due and a second answer is wanted.
 */
function stillOpen(settled: SettledQuestion): boolean {
  return (
    settled.how === 'answered' &&
    !isFixtureAcknowledgement(settled.reply) &&
    settled.reply.clarifying_questions.length > 0
  )
}

/** One recurring question: the gap it rests on, a box for the answer, and Skip. */
function Ask({ question, settled }: { question: HorizonQuestion; settled: SettledQuestion | undefined }) {
  const answerQuestion = useSecond((state) => state.answerQuestion)
  const skipQuestion = useSecond((state) => state.skipQuestion)

  // Fixture mode starts the week box with the sentence the generated answer was
  // made from, so what is sent is what the plan that comes back was made for.
  // Other words still get that plan, and the reply says it was made for these.
  const [text, setText] = useState(
    USING_FIXTURES && question.horizon === 'week' ? FIXTURE_WEEK_ANSWER : '',
  )
  const [busy, setBusy] = useState<'answer' | 'skip' | null>(null)
  // Which action failed rather than a closure over it, so Try again sends the
  // text as it is now and not as it was when the first attempt left.
  const [failed, setFailed] = useState<{ action: 'answer' | 'skip'; what: string } | null>(null)

  const answer = () => {
    const said = text.trim()
    if (!said || busy) return
    setBusy('answer')
    setFailed(null)
    answerQuestion(question, said)
      .catch((error: unknown) => setFailed({ action: 'answer', what: errorLine(error) }))
      .finally(() => setBusy(null))
  }

  const skip = () => {
    if (busy) return
    setBusy('skip')
    setFailed(null)
    skipQuestion(question)
      .catch((error: unknown) => setFailed({ action: 'skip', what: errorLine(error) }))
      .finally(() => setBusy(null))
  }

  const open = settled === undefined || stillOpen(settled)
  const id = `answer-${question.horizon}`

  return (
    <li className={styles.ask} data-settled={!open}>
      <p className={styles.askHead}>
        <span className="label">{HORIZON_NAME[question.horizon]}</span>
        <span className={styles.cadenceNote}>
          not asked again for {question.every_days} days once an answer is planned or it is skipped
        </span>
      </p>
      <p className={styles.question}>{question.question}</p>
      <p className="evidence">{question.evidence}</p>

      {settled && <Settled settled={settled} />}

      {open && (
        <div className={styles.answer}>
          <label htmlFor={id} className={styles.boxLabel}>
            {settled
              ? 'Answer again, with the detail Second asked for.'
              : 'Answer in your own words. Second plans it the same way it plans anything you record.'}
          </label>
          <textarea
            id={id}
            className={styles.box}
            value={text}
            rows={3}
            readOnly={busy !== null}
            onChange={(event) => setText(event.target.value)}
          />

          <div className={styles.send}>
            <button
              type="button"
              className={styles.primary}
              disabled={!text.trim() || busy !== null}
              onClick={answer}
            >
              {busy === 'answer' ? 'Sending' : 'Send the answer'}
            </button>
            <button type="button" className={styles.skip} disabled={busy !== null} onClick={skip}>
              {busy === 'skip' ? 'Skipping' : 'Skip for now'}
            </button>
          </div>

          {busy === 'answer' && !USING_FIXTURES && (
            <p className={styles.working}>Second is planning your answer. This takes tens of seconds.</p>
          )}

          {failed && (
            <Problem what={failed.what} onRetry={failed.action === 'answer' ? answer : skip} />
          )}
        </div>
      )}
    </li>
  )
}

/** What came back, in place of the text box. Recorded, not celebrated. */
function Settled({ settled }: { settled: SettledQuestion }) {
  if (settled.how === 'skipped') {
    const { reply, question } = settled
    return (
      <div className={styles.outcome}>
        <p className="label">Skipped</p>
        <p className={styles.outcomeLine}>
          {isFixtureAcknowledgement(reply)
            ? reply.line
            : `Skipped on ${longDate(reply.asked_on)}. Second asks the ${question.horizon} question again from ${longDate(reply.next_due)}.`}
        </p>
      </div>
    )
  }

  const { reply } = settled
  return (
    <div className={styles.outcome}>
      <p className="label">Answered</p>
      <p className={`evidence ${styles.said}`}>{settled.text}</p>
      {isFixtureAcknowledgement(reply) ? (
        <p className={styles.outcomeLine}>{reply.line}</p>
      ) : (
        <Outcome result={reply} said={settled.text} />
      )}
    </div>
  )
}

/**
 * What Second did with an answer, told from the fields and nothing else.
 *
 * `clarifying_questions` means here what it means on Record: Second was not sure
 * enough to plan. The server then records nothing, so the question stays due
 * and `Ask` keeps the box open below this. A plan is drawn by Record's own
 * `Planned`, because an answer returns the same `ScheduleDecision` a brain dump
 * does, with titles resolved against the graph the same result carried.
 */
function Outcome({ result, said }: { result: IntakeResult; said: string }) {
  const { clarifying_questions: askedBack, schedule } = result
  // Only fixture mode can hand back a plan made from other words: the generated
  // week answer comes back whatever was typed.
  const otherWords = USING_FIXTURES && said !== FIXTURE_WEEK_ANSWER

  return (
    <>
      {otherWords && (
        <p className={styles.outcomeLine}>
          Fixture mode: what follows was generated for “{FIXTURE_WEEK_ANSWER}”, not for the words
          above.
        </p>
      )}

      {askedBack.length > 0 && (
        <>
          <p className={styles.outcomeLine}>
            {schedule
              ? 'Second planned what is below and also asked back:'
              : 'Second needs this before it plans anything, so nothing was placed:'}
          </p>
          <ol className={styles.askedBack}>
            {askedBack.map((asked) => (
              <li key={asked}>{asked}</li>
            ))}
          </ol>
          <p className={styles.outcomeLine}>This question stays open until an answer is planned.</p>
        </>
      )}

      {schedule && <Planned schedule={schedule} graph={result.graph} />}

      {!schedule && askedBack.length === 0 && (
        <p className={styles.outcomeLine}>
          Second returned no plan and no questions, so nothing was placed.
        </p>
      )}

      {USING_FIXTURES && schedule && (
        <p className={styles.outcomeLine}>
          Fixture mode: this plan is shown here only. The other screens still show the checked-in
          data from before it.
        </p>
      )}
    </>
  )
}
