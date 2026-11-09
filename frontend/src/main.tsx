import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import './index.css'

// Interceptor global para anexar X-CSRF-Token automaticamente em requisições de mutação
const originalFetch = window.fetch;
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const method = (init?.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const csrfMatch = document.cookie.match(/(^|;\s*)mockbird_csrf=([^;]+)/);
    if (csrfMatch && csrfMatch[2]) {
      const headers = new Headers(init?.headers || {});
      if (!headers.has('X-CSRF-Token')) {
        headers.set('X-CSRF-Token', csrfMatch[2]);
      }
      init = { ...init, headers };
    }
  }
  return originalFetch(input, init);
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

