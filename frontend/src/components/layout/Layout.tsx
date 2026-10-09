import { Outlet } from 'react-router-dom'
import { TopNav } from './TopNav'

export function Layout() {
  return (
    <div className="min-h-screen bg-bg">
      <TopNav />
      <main className="container-page py-10">
        <Outlet />
      </main>
    </div>
  )
}
