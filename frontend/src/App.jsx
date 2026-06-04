import { useState } from 'react'
import Chat from './components/Chat'
import Dashboard from './components/Dashboard'
import Capture from './components/Capture'
import './App.css'

const TABS = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'dashboard', label: 'Dashboard', icon: '📋' },
  { id: 'capture', label: 'Capture', icon: '✏️' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')

  return (
    <div className="app">
      {/* Desktop sidebar */}
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__logo">⚡</span>
          <span className="sidebar__title">akash.planner</span>
        </div>
        <nav className="sidebar__nav">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`sidebar__link ${activeTab === tab.id ? 'sidebar__link--active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="sidebar__link-icon">{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="main">
        {activeTab === 'chat' && <Chat />}
        {activeTab === 'dashboard' && <Dashboard />}
        {activeTab === 'capture' && <Capture />}
      </main>

      {/* Mobile bottom tab bar */}
      <nav className="bottom-nav">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`bottom-nav__tab ${activeTab === tab.id ? 'bottom-nav__tab--active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="bottom-nav__icon">{tab.icon}</span>
            <span className="bottom-nav__label">{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}
