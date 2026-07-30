import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import api, { tokenStorage } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";

// 顧客登入後允許被導回的路徑。見 handleLogin 的說明。
const CUSTOMER_REDIRECTS = ['/checkout', '/orders']

function Auth() {
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState('login')
  const [role, setRole] = useState('customer')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)

  const switchMode = (nextMode) => {
    setMode(nextMode)
    setError(null)
    setSuccessMessage(null)
  }

  const switchRole = (nextRole) => {
    setRole(nextRole)
    setError(null)
    setSuccessMessage(null)
  }

  const handleLogin = async () => {
    const res = await api.post('/api/auth/login', {
      role,
      email,
      password,
    })
    // 一併保存 refresh token：access token 只有 15 分鐘，
    // 沒有它使用者每 15 分鐘就會被登出
    tokenStorage.save(res.data)

    if (role === 'merchant') {
      navigate('/merchant', { replace: true })
    } else {
      // 只採用屬於顧客區的來源路徑。
      //
      // 商家後台在登出與遇到認證錯誤時，都會帶著 state.from = '/merchant'
      // 導回登入頁。若這裡無條件沿用 from，「登出商家 → 用顧客帳號登入」
      // 就會把顧客送進商家後台——頁面渲染得出來（那裡只檢查有沒有 token，
      // 沒檢查角色），但每個 API 呼叫都會被後端以 403 擋掉。
      //
      // 用允許清單而非排除清單：日後新增商家路由時不必回來補，
      // 未列入的來源一律退回首頁，是安全的預設行為。
      const from = location.state?.from
      navigate(CUSTOMER_REDIRECTS.includes(from) ? from : '/', { replace: true })
    }
  }

  const handleRegister = async () => {
    await api.post('/api/auth/register', {
      role,
      name: username,
      email,
      password,
    })
    setSuccessMessage('註冊成功，請登入')
    switchMode('login')
    setPassword('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setIsSubmitting(true)

    try {
      if (mode === 'login') {
        await handleLogin()
      } else {
        await handleRegister()
      }
    } catch (err) {
      setError(extractErrorMessage(err, '發生錯誤，請稍後再試'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-md">
        <div className="mb-6 flex rounded-full bg-gray-100 p-1">
          <button
            type="button"
            onClick={() => switchMode('login')}
            className={`flex-1 rounded-full py-2 text-sm font-medium transition-colors ${
              mode === 'login'
                ? 'bg-orange-500 text-white shadow'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            登入
          </button>
          <button
            type="button"
            onClick={() => switchMode('register')}
            className={`flex-1 rounded-full py-2 text-sm font-medium transition-colors ${
              mode === 'register'
                ? 'bg-orange-500 text-white shadow'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            註冊
          </button>
        </div>

        <div className="mb-4 flex justify-center gap-2 text-sm">
          <button
            type="button"
            onClick={() => switchRole('customer')}
            className={`rounded-full px-4 py-1.5 font-medium transition-colors ${
              role === 'customer'
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-500 hover:text-gray-700'
            }`}
          >
            顧客
          </button>
          <button
            type="button"
            onClick={() => switchRole('merchant')}
            className={`rounded-full px-4 py-1.5 font-medium transition-colors ${
              role === 'merchant'
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-500 hover:text-gray-700'
            }`}
          >
            商家
          </button>
        </div>

        <h1 className="mb-4 text-center text-xl font-bold text-gray-900">
          {role === 'merchant'
            ? mode === 'login'
              ? '商家登入'
              : '商家註冊'
            : mode === 'login'
              ? '會員登入'
              : '會員註冊'}
        </h1>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && (
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                使用者名稱
              </label>
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
              />
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              電子信箱
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              密碼
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
            />
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}
          {successMessage && (
            <p className="text-sm text-green-600">{successMessage}</p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-full bg-orange-500 py-2.5 font-medium text-white shadow hover:bg-orange-600 transition-colors disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {isSubmitting ? '處理中...' : mode === 'login' ? '登入' : '註冊'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default Auth
