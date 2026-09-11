import { useEffect } from 'react'

import { USING_FIXTURES } from './api/client'
import { Goals } from './screens/Goals'
import { LivingGraphScreen } from './screens/LivingGraphScreen'
import { Record } from './screens/Record'
import { Today } from './screens/Today'
import { useSecond, type Screen } from './store/useSecond'
import styles from './App.module.css'

/** Four screens. The order is the order of the day: speak, see, do, decide. */
const SCREENS: { id: Screen; label: string }[] = [
  { id: 'record', label: 'Record' },
  { id: 'graph', label: 'Living Graph' },
  { id: 'today', label: 'Today' },
  { id: 'goals', label: 'Goals' },
]

export function App() {
  const screen = useSecond((state) => state.screen)
  const show = useSecond((state) => state.show)
  const loadGraph = useSecond((state) => state.loadGraph)
  const loadBrief = useSecond((state) => state.loadBrief)

  // Both, once, at startup. The Living Graph and Today are the two screens a
  // judge will flip between, and neither should ever be caught loading.
  useEffect(() => {
    void loadGraph()
    void loadBrief()
  }, [loadGraph, loadBrief])

  return (
    <div className={styles.shell}>
      <nav className={styles.rail} aria-label="Screens">
        <div className={styles.wordmark}>Second</div>

        <ul className={styles.nav}>
          {SCREENS.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={styles.navItem}
                aria-current={screen === item.id ? 'page' : undefined}
                onClick={() => show(item.id)}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>

        {USING_FIXTURES && (
          <p className={styles.source} title="VITE_SOURCE=fixtures">
            fixtures
            <span className={styles.sourceNote}>
              generated from the real graph, not the live backend
            </span>
          </p>
        )}
      </nav>

      <main className={styles.screen}>
        {screen === 'record' && <Record />}
        {screen === 'graph' && <LivingGraphScreen />}
        {screen === 'today' && <Today />}
        {screen === 'goals' && <Goals />}
      </main>
    </div>
  )
}
