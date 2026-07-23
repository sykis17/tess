import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { LandingPage } from './landing/LandingPage.tsx'

function resolveRootView(): 'landing' | 'chat' {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/chat' || path.startsWith('/chat/')) {
    return 'chat'
  }
  return 'landing'
}

const view = resolveRootView()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {view === 'landing' ? <LandingPage /> : <App />}
  </StrictMode>,
)
