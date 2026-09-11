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
 * a task at 09:00 that Today shows at 08:00.
 *
 * **So nothing here parses a datetime. Every formatter reads the characters.**
 * Both shapes already carry the wall-clock time the person will read off their
 * own calendar -- the naive one because that is how the graph stores it, the
 * aware one because PLATFORM puts everything crossing the API boundary through
 * `Clock.local()` first. The offset on an aware string says which zone that
 * was; it is not an instruction to convert.
 *
 * The one remaining `Date` is `Date.UTC(y, m, d)` for a weekday name, which
 * takes no time and no zone. Nothing in this module can shift an hour, and
 * nothing in it behaves differently depending on where the viewer is.
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

const WALL_CLOCK = /^\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})/

/** `08:00` from either shape, read off the characters and never parsed.
 *
 * **Both shapes are sliced, including the timezone-aware one, and that is the
 * correction that matters here.** The first version handed an aware string to
 * `Date` and read `getHours()`, which is the *browser's* zone -- so Today's
 * 08:00 block rendered as 00:00 for a viewer in US-Pacific, and the Goals
 * screen printed a date sliced from the characters beside an hour parsed in
 * another zone: `Friday 11 September, 11:00` for a moment that was 19:00.
 *
 * Slicing is correct because of what the contract guarantees. `ScheduledBlock.
 * start` is already in the user's own zone -- PLATFORM puts everything crossing
 * the API boundary through `Clock.local()` -- so the characters after the `T`
 * are the wall-clock time the person reads off their calendar, and the offset
 * is there to say which zone that was, not to be converted out of.
 *
 * So there is one rule for both shapes: the hour on screen is the hour in the
 * string. Nothing in this module depends on where the browser is.
 */
export function clockTime(iso: string): string {
  const match = WALL_CLOCK.exec(iso)
  return match ? match[1] : '--:--'
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
