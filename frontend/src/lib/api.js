import axios from 'axios'

/**
 * 全專案共用的 API client。
 *
 * 取代原本「直接用全域 axios + 相對路徑」的做法。相對路徑只有在本機透過
 * Vite dev proxy 時才會通；部署到 Vercel 之後 `/api/orders` 會打到 Vercel
 * 自己的網域而得到 404，因此必須有可設定的 baseURL。
 */

const ACCESS_TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'

// 本機留空 → 走 vite.config.js 的 dev proxy
// 正式環境設為後端網址，例如 https://ordering-backend.onrender.com
const baseURL = import.meta.env.VITE_API_BASE_URL ?? ''

const api = axios.create({
  baseURL,
  // 後端在 Render 免費方案上休眠後需要 30~60 秒冷啟動，
  // 預設的逾時時間會讓第一個請求還沒等到服務醒來就失敗。
  timeout: 90_000,
})

export const tokenStorage = {
  get access() {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  },
  save({ access_token, refresh_token }) {
    if (access_token) localStorage.setItem(ACCESS_TOKEN_KEY, access_token)
    if (refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },
  get isLoggedIn() {
    return !!localStorage.getItem(ACCESS_TOKEN_KEY)
  },
}

api.interceptors.request.use((config) => {
  const token = tokenStorage.access
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 這些端點自己就是處理認證的，401 時不該再去 refresh
const AUTH_ENDPOINTS = ['/api/auth/login', '/api/auth/token', '/api/auth/refresh', '/api/auth/register']

const isAuthEndpoint = (url = '') => AUTH_ENDPOINTS.some((path) => url.includes(path))

/**
 * 進行中的 refresh 請求。
 *
 * 這個變數是整段邏輯的關鍵。access token 只有 15 分鐘，過期後頁面上同時發出的
 * 多個請求會一起收到 401；若每個都各自去 refresh，後端的「refresh token 重用
 * 偵測」會在第二個請求就判定 token 外洩，直接撤銷整條 token family——
 * 使用者不是被續期，而是被強制登出。
 *
 * 因此所有 401 共用同一個 refresh promise，只送出一次換發請求。
 */
let refreshPromise = null

async function refreshAccessToken() {
  const refreshToken = tokenStorage.refresh
  if (!refreshToken) throw new Error('沒有 refresh token')

  // 刻意用未經攔截器包裝的 axios，避免 refresh 自己失敗時再次觸發攔截器
  const { data } = await axios.post(
    `${baseURL}/api/auth/refresh`,
    { refresh_token: refreshToken },
    { timeout: 90_000 },
  )
  tokenStorage.save(data)
  return data.access_token
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error

    if (
      response?.status !== 401 ||
      config?._retried ||
      isAuthEndpoint(config?.url) ||
      !tokenStorage.refresh
    ) {
      return Promise.reject(error)
    }

    config._retried = true

    try {
      refreshPromise = refreshPromise ?? refreshAccessToken()
      const accessToken = await refreshPromise
      config.headers.Authorization = `Bearer ${accessToken}`
      return api(config)
    } catch (refreshError) {
      // refresh 也失敗代表這個登入階段真的結束了（過期、被撤銷、或偵測到重用）
      tokenStorage.clear()
      if (!window.location.pathname.startsWith('/auth')) {
        window.location.assign('/auth')
      }
      return Promise.reject(refreshError)
    } finally {
      refreshPromise = null
    }
  },
)

export default api
