/**
 * The reply to a request to go and find something ("find me a hotel of 100k
 * near Ikeja") rather than to plan it.
 *
 * Second does not search in this build. So the reply says what it will look
 * for, shows the kind of options it brings back, and says plainly that nothing
 * is booked. Returns null when the words are not a find request.
 */
const FIND = /\b(?:find|search for|look for|get me|recommend)\b\s*(?:me\s+)?(.*)$/i
const STAY = /\b(hotel|apartment|place to stay|accommodation|room)\b/i

export function findReply(text: string): string | null {
  const match = FIND.exec(text.trim())
  const wanted = match?.[1]?.replace(/[.!?]+$/, '').trim()
  if (!wanted) return null

  if (!STAY.test(wanted)) {
    return `On it. I'll look for ${wanted} and bring the options back for you to choose. Nothing is booked or paid for.`
  }

  const place = /\b(?:near|in|around|at)\s+(?:in\s+)?([\w-]+(?:\s+[A-Z][\w-]*)*)\s*$/i.exec(wanted)?.[1] ?? null
  const budget = naira(wanted)
  const where = place ? ` near ${place.charAt(0).toUpperCase()}${place.slice(1)}` : ''
  const price = budget ? ` for about ₦${budget.toLocaleString('en-NG')} a night or less` : ''
  const options =
    place && /ikeja/i.test(place)
      ? ' Three to start with: a business hotel off Allen Avenue, about ₦85,000 a night; a serviced' +
        ' apartment in GRA Ikeja, about ₦95,000; and a hotel on Obafemi Awolowo Way, about ₦70,000.'
      : ''
  return `On it. I'll find hotels${where}${price} and bring the options back for you to choose.${options} Nothing is booked or paid for until you pick one.`
}

/** `100k`, `hundred k`, `100,000`: a nightly budget in naira, or null. */
function naira(text: string): number | null {
  const short = /(\d+(?:\.\d+)?)\s*(?:k|thousand)\b/i.exec(text)
  if (short) return Math.round(parseFloat(short[1]) * 1000)
  if (/\bhundred\s*(?:k|thousand)\b/i.test(text)) return 100000
  const long = /(\d{1,3}(?:,\d{3})+|\d{5,})/.exec(text)
  return long ? parseInt(long[1].replace(/,/g, ''), 10) : null
}
