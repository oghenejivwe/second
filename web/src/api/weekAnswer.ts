/**
 * The sentence `question-answer-week.json` was generated from. Fixture mode only.
 *
 * The payload carries the plan, the graph and any questions back, and not the
 * words, so the sentence has to live somewhere in the browser. This file is that
 * one place: the Memory screen fills the week box with it and says so when the
 * words sent differ, because a plan shown under a sentence it was not made from
 * is a plan for a different sentence.
 *
 * It is `WEEK_ANSWER` in web/scripts/make_fixtures.py, and
 * tests/platform/test_make_fixtures.py fails when the two disagree, so a new
 * answer fixture cannot ship under the old sentence.
 */
export const FIXTURE_WEEK_ANSWER =
  'Confirm the hotel and buy travel insurance by Saturday 19 September.'
