/**
 * The two datetime shapes the contract sends, kept apart on purpose.
 *
 * `ScheduledBlock.start` is timezone-AWARE -- `2026-09-10T08:00:00+01:00`.
 * `Task.scheduled_slots` are NAIVE -- `2026-09-10T08:00:00`, no offset.
 *
 * The asymmetry is deliberate and PLATFORM states it on the field itself: the
 * Living Graph stores wall-clock time because a plan is what the person reads
 * off their own calendar, and storing it as UTC would move the plan when they
 * travel. Anything crossing the API boundary is made aware by `Clock.local()`.
 *
 * `new Date('2026-09-10T08:00:00')` is interpreted in the *browser's* timezone,
 * which is not necessarily the user's. So a naive slot and an aware block can
 * describe the same moment and compare unequal, and the Living Graph would show
 * a task at 09:00 that Today shows at 08:00. **This module never converts
 * between the two.** Naive strings are formatted by reading their characters;
 * aware strings go through `Date`. Nothing here can silently shift an hour.
 */

/** An ISO string carrying an offset, e.g. `2026-09-10T08:00:00+01:00`. */
export type AwareIso = string

/** An ISO string with no offset, e.g. `2026-09-10T08:00:00`. */
export type NaiveIso = string

const NAIVE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/

export function isNaive(iso: string): boolean {
  return NAIVE.test(iso)
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

/** `08:00` from either shape, without moving the clock.
 *
 * A naive string is sliced, not parsed: the characters already say what the
 * person will read off their calendar, and handing them to `Date` would
 * reinterpret them in whatever zone the browser happens to be in.
 */
export function clockTime(iso: string): string {
  const naive = NAIVE.exec(iso)
  if (naive) return `${naive[4]}:${naive[5]}`

  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return '--:--'
  return `${pad(at.getHours())}:${pad(at.getMinutes())}`
}

/** `Thursday 10 September` from a date or datetime string. */
export function longDate(iso: string): string {
  const parts = dateParts(iso)
  if (!parts) return iso
  const { year, month, day } = parts
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]
  return `${weekday} ${day} ${MONTHS[month - 1]}`
}

/** `10 Sep` -- for a list where the year is obvious and the weekday is noise. */
export function shortDate(iso: string): string {
  const parts = dateParts(iso)
  if (!parts) return iso
  return `${parts.day} ${MONTHS[parts.month - 1].slice(0, 3)}`
}

/** `Thu` -- for the check-in, where the day of the week is the useful part. */
export function weekdayShort(iso: string): string {
  const parts = dateParts(iso)
  if (!parts) return ''
  const { year, month, day } = parts
  return WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()].slice(0, 3)
}

/** `1h`, `45 min`, `1h 30`. Durations are minutes in the contract. */
export function duration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours}h ${rest}` : `${hours}h`
}

/** `3 slots · 3h` -- what retiring a goal released. */
export function freedTime(slots: number, minutes: number): string {
  const unit = slots === 1 ? 'slot' : 'slots'
  return `${slots} ${unit} · ${duration(minutes)}`
}

/** The calendar date, as `YYYY-MM-DD`, from either shape. Never a `Date`. */
export function dateKey(iso: string): string {
  return iso.slice(0, 10)
}

/** Minutes from midnight, for laying a day out proportionally. */
export function minutesIntoDay(iso: string): number {
  const [hh, mm] = clockTime(iso).split(':')
  return Number(hh) * 60 + Number(mm)
}

/** Sort comparator for slots of the SAME shape. Lexicographic, which is correct
 * for ISO 8601 within one shape and one offset, and avoids `Date` entirely. */
export function bySlot(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

function dateParts(iso: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return null
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) }
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}
