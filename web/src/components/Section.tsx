import type { ReactNode } from 'react'

import styles from './Section.module.css'

/**
 * A labelled band of content, separated by a rule rather than a card.
 *
 * `count` is rendered beside the label because most of these sections are
 * allowed to be empty and the number is how a reader tells "nothing here" from
 * "not loaded". `aside` carries whatever one line belongs next to the heading.
 */
export function Section({
  label,
  count,
  aside,
  children,
}: {
  label: string
  count?: number
  aside?: ReactNode
  children: ReactNode
}) {
  return (
    <section className={styles.section}>
      <header className={styles.head}>
        <h2 className={styles.label}>
          {label}
          {count !== undefined && <span className={styles.count}>{count}</span>}
        </h2>
        {aside && <div className={styles.aside}>{aside}</div>}
      </header>
      {children}
    </section>
  )
}
