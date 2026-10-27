import { useState, Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'

import { SystemReadinessProvider } from './components/SystemReadinessContext'
import { SystemReadinessBanner } from './components/SystemReadinessBanner'

import ChatPage from './pages/ChatPage.tsx'
import SecurityPage from './pages/SecurityPage.tsx'
import AlertsPage from './pages/AlertsPage.tsx'
import './App.css'

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '24px', margin: '20px', backgroundColor: '#fee2e2', border: '1px solid #fecaca', borderRadius: '8px', color: '#991b1b', fontFamily: 'sans-serif' }}>
          <h3 style={{ marginTop: 0 }}>The page crashed during render:</h3>
          <p><strong>{this.state.error?.toString()}</strong></p>
          <p style={{ fontSize: '14px', color: '#555' }}>Check your browser's Developer Tools Console (F12) for the full stack trace.</p>
        </div>
      );
    }

    return this.props.children; 
  }
}

function App() {
  const [currentPage, setCurrentPage] = useState<'chat' | 'security' | 'alerts'>('chat')

  return (
    <SystemReadinessProvider>
      <header className="app-header">
        <div className="header-inner">
          <div className="header-content">
            <div>
              <h1 className="header-text">LLASER</h1>
              <p className="header-subtitle">RAG chat with prompt-injection defenses</p>
            </div>
          </div>
          <nav className="header-nav">
            <button 
              className={`nav-button ${currentPage === 'chat' ? 'active' : ''}`}
              onClick={() => setCurrentPage('chat')}
            >
              Chat
            </button>
            <button 
              className={`nav-button ${currentPage === 'security' ? 'active' : ''}`}
              onClick={() => setCurrentPage('security')}
            >
              Controls
            </button>
            <button 
              className={`nav-button ${currentPage === 'alerts' ? 'active' : ''}`}
              onClick={() => setCurrentPage('alerts')}
            >
              Alerts
            </button>
          </nav>
        </div>
      </header>

      <div className="app-readiness-shell">
        <SystemReadinessBanner />
      </div>
      
      <main className="app-main">
        <div hidden={currentPage !== 'chat'}>
          <ErrorBoundary>
            <ChatPage />
          </ErrorBoundary>
        </div>
        {currentPage === 'security' && (
          <ErrorBoundary>
            <SecurityPage />
          </ErrorBoundary>
        )}
        {currentPage === 'alerts' && (
          <ErrorBoundary>
            <AlertsPage />
          </ErrorBoundary>
        )}
      </main>
    </SystemReadinessProvider>
  )
}

export default App