import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ArchitecturePage } from './ArchitecturePage'
import './architecture.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ArchitecturePage />
  </StrictMode>,
)
