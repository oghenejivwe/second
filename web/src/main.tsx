import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// The faces load before the stylesheets that name them, so the first paint
// already knows the weights exist. Only the weights the tokens use are
// imported: Open Runde carries headings, navigation and body copy, and Inter
// is kept to the small UI labels where its narrower forms read better.
import '@fontsource/open-runde/400.css'
import '@fontsource/open-runde/500.css'
import '@fontsource/open-runde/600.css'
import '@fontsource/open-runde/700.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'

import { App } from './App'
import './styles/base.css'
import './styles/flow.css'

const host = document.getElementById('root')
if (!host) throw new Error('index.html is missing #root')

createRoot(host).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
