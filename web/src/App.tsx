import { useEffect } from 'react'

import { USING_FIXTURES } from './api/client'
import { Goals } from './screens/Goals'
import { LivingGraphScreen } from './screens/LivingGraphScreen'
import { MemoryScreen } from './screens/MemoryScreen'
import { Record } from './screens/Record'
import { ScheduleScreen } from './screens/ScheduleScreen'
import { Today } from './screens/Today'
import { useSecond, type Screen } from './store/useSecond'
import styles from './App.module.css'

/** Six screens. The order is the order of the day: speak, see the plan, today,
 * the days ahead, what to remember, decide. Schedule sits directly after Today
 * because it is the same list carried forward, and the two are the pair a
 * person flips between. Memory follows them because what is waiting on you and
 * what is due reads best once the days are in view, and its week and month
 * questions are about those days. Goals stays last. */
const SCREENS: { id: Screen; label: string }[] = [
  { id: 'record', label: 'Record' },
  { id: 'graph', label: 'Living Graph' },
  { id: 'today', label: 'Today' },
  { id: 'schedule', label: 'Schedule' },
  { id: 'memory', label: 'Memory' },
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
        {screen === 'schedule' && <ScheduleScreen />}
        {screen === 'memory' && <MemoryScreen />}
        {screen === 'goals' && <Goals />}
      </main>
    </div>
  )
}
