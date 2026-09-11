/**
 * Turn the shared pydantic contract into TypeScript.
 *
 * The models in `src/second/core/models.py` are the source of truth for every
 * payload the browser sees, so the types are generated from them rather than
 * typed by hand. Hand-written mirrors of someone else's types drift, and they
 * drift silently: the screens keep compiling against a shape the API stopped
 * sending.
 *
 *   python web/scripts/make_fixtures.py    # emits src/types/contract.schema.json
 *   node   web/scripts/gen-types.mjs       # emits src/types/contract.ts
 *
 * The schema is generated in pydantic's `serialization` mode, which is what the
 * API actually sends -- a field with a default is optional on the way in and
 * always present on the way out, and the screens only ever see the way out.
 *
 * ## Two things the schema gets wrong for our purposes, both fixed below
 *
 * **Titles.** pydantic writes a `title` onto every single field ("At", "RunId",
 * "SlipCount"), and json-schema-to-typescript treats a title as a request for a
 * named type. A straight compile emits 173 exported types, 140 of which are
 * aliases like `type Title1 = string`. So field-level titles are stripped, and
 * only the `$defs` entries -- the actual models -- keep theirs.
 *
 * **Required.** Neither schema mode marks a defaulted field as required, so
 * `DailyBrief.blocks` compiles to `blocks?: ScheduledBlock[]`. That is wrong for
 * a client: `model_dump(mode="json")` emits every field on every model, always,
 * so the browser never sees one missing. Left alone it would put a `?.` on most
 * accesses in the app and teach the screens to treat "the API forgot to send
 * today's schedule" as a normal case. Every property is therefore marked
 * required, which leaves nullability where it belongs -- `check_in: CheckIn |
 * null` is present and may be null, which is exactly the contract.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { compile } from 'json-schema-to-typescript'

const here = dirname(fileURLToPath(import.meta.url))
const schemaPath = resolve(here, '..', 'src', 'types', 'contract.schema.json')
const outPath = resolve(here, '..', 'src', 'types', 'contract.ts')

const schema = JSON.parse(readFileSync(schemaPath, 'utf8'))
const modelNames = Object.keys(schema.$defs ?? {})

/** Strip `title` everywhere except from the model definitions themselves.
 *
 * The string check is load-bearing. `Goal`, `Route`, `Task` and `ScheduledBlock`
 * all have a field *called* `title`, so a blind `delete node.title` walks into
 * the `properties` map and removes the field itself -- silently, leaving types
 * that compile and screens that render undefined. The keyword is always a
 * string; a field schema is always an object.
 */
function stripFieldTitles(node, keep = false) {
  if (Array.isArray(node)) return node.forEach((item) => stripFieldTitles(item))
  if (!node || typeof node !== 'object') return
  if (!keep && typeof node.title === 'string') delete node.title
  for (const [key, value] of Object.entries(node)) {
    if (key === '$defs') {
      for (const def of Object.values(value)) stripFieldTitles(def, true)
    } else {
      stripFieldTitles(value)
    }
  }
}

stripFieldTitles(schema, true)
delete schema.title

/** Every field the API sends is present, so every property is required. */
for (const def of Object.values(schema.$defs ?? {})) {
  if (def && def.type === 'object' && def.properties) {
    def.required = Object.keys(def.properties)
  }
}

const banner = `/* eslint-disable */
/**
 * GENERATED. Do not edit.
 *
 * Source: src/second/core/models.py, via pydantic's serialization-mode JSON
 * Schema. Regenerate with:
 *
 *   python web/scripts/make_fixtures.py && node web/scripts/gen-types.mjs
 *
 * Datetimes arrive as ISO 8601 strings. Two shapes, and the difference matters:
 * ScheduledBlock.start carries an offset, Task.scheduled_slots do not. See
 * src/lib/datetime.ts -- never compare one against the other directly.
 */`

const ts = await compile(schema, 'SecondContract', {
  bannerComment: banner,
  additionalProperties: false,
  unknownAny: true,
  unreachableDefinitions: true,
  enableConstEnums: false,
  format: true,
  style: { printWidth: 96, singleQuote: true, semi: false },
})

// The wrapper interface exists only to give the compiler an object schema it will
// enter, so that every $defs entry is reached. Nothing imports it.
const cleaned = ts.replace(/export interface SecondContract \{[\s\S]*?\n\}\n+/, '')

writeFileSync(outPath, cleaned, 'utf8')

const emitted = [...cleaned.matchAll(/^export (?:interface|type) (\w+)/gm)].map((match) => match[1])
console.log(`wrote ${outPath}`)
console.log(`  ${emitted.length} exported types from ${modelNames.length} models`)

const missing = modelNames.filter((name) => !emitted.includes(name))
if (missing.length) {
  console.error(`\nMISSING ${missing.length} of ${modelNames.length}: ${missing.join(', ')}`)
  process.exit(1)
}

const extra = emitted.filter((name) => !modelNames.includes(name))
if (extra.length) console.log(`  plus ${extra.length} helper types: ${extra.join(', ')}`)
