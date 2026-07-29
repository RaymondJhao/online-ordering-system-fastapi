import { useEffect, useState } from 'react'
import api from '../lib/api'

/**
 * 後端喚醒狀態提示。
 *
 * 為什麼需要這個元件：後端部署在 Render 免費方案，閒置 15 分鐘後會休眠，
 * 下一個請求需要 30~60 秒冷啟動。這個專案刻意**不做定時保溫**——
 * 它是求職作品集，錄取後就不需要維持 24/7 熱機，而保溫會用掉幾乎全部的
 * 免費額度（每月 750 instance hours，一個月有 730 小時）。
 *
 * 既然選擇接受冷啟動，就該把它處理得體面：
 *
 * 1. 一進站就在背景送出喚醒請求，讓使用者瀏覽菜單的同時後端已經在啟動
 * 2. 超過 2 秒還沒回應才顯示提示，避免熱機狀態下閃一下橫幅反而干擾
 * 3. 明確告知預期等待時間，而不是讓畫面空白轉圈
 *
 * 探測目標是 /health/live 而非 /health——前者不碰資料庫與 Redis，
 * 純粹確認服務是否醒著。
 */

const SHOW_BANNER_AFTER_MS = 2000

export default function BackendStatusBanner() {
  const [isWaking, setIsWaking] = useState(false)
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    let cancelled = false
    const showTimer = setTimeout(() => {
      if (!cancelled) setIsWaking(true)
    }, SHOW_BANNER_AFTER_MS)

    api
      .get('/health/live')
      .catch(() => {
        // 喚醒失敗不需要打擾使用者——真正的錯誤會由實際的 API 呼叫回報
      })
      .finally(() => {
        if (cancelled) return
        clearTimeout(showTimer)
        setIsWaking(false)
      })

    return () => {
      cancelled = true
      clearTimeout(showTimer)
    }
  }, [])

  useEffect(() => {
    if (!isWaking) return
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [isWaking])

  if (!isWaking) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="sticky top-0 z-50 flex items-center justify-center gap-3 bg-amber-50 px-4 py-2 text-sm text-amber-900 border-b border-amber-200"
    >
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
      <span>
        後端服務喚醒中，約需 30–60 秒（已等待 {seconds} 秒）。
        <span className="hidden sm:inline">
          {' '}此為免費方案的休眠機制，非系統異常。
        </span>
      </span>
    </div>
  )
}
