import { describe, expect, it } from 'vitest'
import { extractErrorMessage } from '../lib/errors'

/**
 * 遷移到 FastAPI 後錯誤格式從 `message` 變成 `detail`，
 * 而且 422 的 detail 是陣列不是字串。這些測試守住那個轉換。
 */
describe('extractErrorMessage', () => {
  it('讀得到 FastAPI 的 detail 字串', () => {
    const error = { response: { status: 409, data: { detail: '此信箱已被註冊' } } }
    expect(extractErrorMessage(error)).toBe('此信箱已被註冊')
  })

  it('仍相容 Flask 時代的 message 欄位', () => {
    const error = { response: { status: 400, data: { message: '舊格式錯誤' } } }
    expect(extractErrorMessage(error)).toBe('舊格式錯誤')
  })

  it('把 422 的驗證錯誤陣列攤平成可讀訊息', () => {
    const error = {
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'email'], msg: 'value is not a valid email address' },
            { loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
          ],
        },
      },
    }
    expect(extractErrorMessage(error)).toBe(
      'email：value is not a valid email address；password：String should have at least 8 characters',
    )
  })

  it('429 會帶出 Retry-After 的秒數', () => {
    const error = {
      response: { status: 429, data: { detail: 'x' }, headers: { 'retry-after': '42' } },
    }
    expect(extractErrorMessage(error)).toBe('操作過於頻繁，請於 42 秒後再試')
  })

  it('逾時會提示可能是後端冷啟動', () => {
    expect(extractErrorMessage({ code: 'ECONNABORTED' })).toMatch(/喚醒/)
  })

  it('沒有 response 時視為連線問題', () => {
    expect(extractErrorMessage(new Error('Network Error'))).toMatch(/無法連線/)
  })

  it('格式無法辨識時回傳指定的預設訊息', () => {
    const error = { response: { status: 500, data: {} } }
    expect(extractErrorMessage(error, '自訂預設')).toBe('自訂預設')
  })
})
