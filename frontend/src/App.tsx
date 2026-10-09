import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { AuthProvider } from '@/auth/AuthProvider'
import { RequireAuth, StaffOnly } from '@/components/layout/Guards'
import { Layout } from '@/components/layout/Layout'
import { ResearchLab } from '@/pages/ResearchLab'
import { ResearchRunDetail } from '@/pages/ResearchRunDetail'
import { Settings } from '@/pages/Settings'
import { Login } from '@/pages/Login'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 2,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="login" element={<Login />} />
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route index element={<Navigate to="/research-lab" replace />} />
                <Route path="research-lab" element={<StaffOnly><ResearchLab /></StaffOnly>} />
                <Route path="research-lab/:id" element={<StaffOnly><ResearchRunDetail /></StaffOnly>} />
                <Route path="settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/research-lab" replace />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
