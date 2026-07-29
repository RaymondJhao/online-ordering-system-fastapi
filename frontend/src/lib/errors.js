/**
 * 從 API 錯誤中取出可以顯示給使用者的訊息。
 *
 * 遷移到 FastAPI 之後錯誤格式變了，這是必須集中處理的原因：
 *
 * - Flask 版回 `{"message": "..."}`
 * - FastAPI 回 `{"detail": "..."}`
 * - FastAPI 的 422 驗證錯誤回 `{"detail": [{loc, msg, type}, ...]}`——
 *   是**陣列不是字串**，直接塞進 JSX 會顯示成 [object Object]
 *
 * 前端原本各處都寫 `err.response?.data?.message ?? '發生錯誤'`，
 * 遷移後那個判斷永遠取不到值，所有錯誤都會退化成通用訊息，
 * 使用者看不到「此信箱已被註冊」「庫存不足」這些真正有用的內容。
 */

const FALLBACK = '發生錯誤，請稍後再試'

export function extractErrorMessage(error, fallback = FALLBACK) {
  // 冷啟動或斷網：沒有 response 物件
  if (!error?.response) {
    if (error?.code === 'ECONNABORTED') {
      return '請求逾時，後端服務可能正在喚醒中，請稍後再試'
    }
    return '無法連線到伺服器，請確認網路狀態'
  }

  const { status, data } = error.response

  if (status === 429) {
    const retryAfter = error.response.headers?.['retry-after']
    return retryAfter
      ? `操作過於頻繁，請於 ${retryAfter} 秒後再試`
      : '操作過於頻繁，請稍後再試'
  }

  const detail = data?.detail ?? data?.message

  if (typeof detail === 'string') return detail

  // FastAPI 422：detail 是驗證錯誤的陣列
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null
        return field ? `${field}：${item?.msg}` : item?.msg
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }

  return fallback
}
