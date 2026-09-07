/**
 * AStock ETF Dashboard — 认证模块
 * - JWT token 管理（localStorage）
 * - 登录 / 登出 / 密码修改
 * - API 请求自动附带 Authorization header
 * - 401 响应自动跳转登录页
 */
'use strict';

const Auth = (function () {
  // ── Private state ──
  let _token = null;
  let _user = null;

  // ── Token helpers ──

  function _loadToken() {
    try { return localStorage.getItem('dash_token'); }
    catch (e) { return null; }
  }

  function _saveToken(t) {
    _token = t;
    try { localStorage.setItem('dash_token', t); }
    catch (e) { /* localStorage 不可用 */ }
  }

  function _clearToken() {
    _token = null;
    _user = null;
    try { localStorage.removeItem('dash_token'); }
    catch (e) { /* ignore */ }
  }

  function _isTokenExpired(token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return (payload.exp * 1000) < Date.now();
    } catch (e) {
      return true;
    }
  }

  // ── Public API ──

  function init() {
    const saved = _loadToken();
    if (saved && !_isTokenExpired(saved)) {
      _token = saved;
      // Decode user info from token
      try {
        const payload = JSON.parse(atob(saved.split('.')[1]));
        _user = {
          username: payload.sub,
          display_name: payload.display,
          role: payload.role,
        };
      } catch (e) {
        _clearToken();
      }
    } else if (saved) {
      // Token expired
      _clearToken();
    }
    return isLoggedIn();
  }

  function isLoggedIn() {
    return !!_token && !_isTokenExpired(_token);
  }

  function getUser() {
    return _user;
  }

  function getHeaders() {
    if (!_token) return {};
    return { 'Authorization': 'Bearer ' + _token, 'Content-Type': 'application/json' };
  }

  // ── Login / Logout ──

  async function login(username, password) {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '登录失败');
    }
    _saveToken(data.access_token);
    _user = data.user;
    return data;
  }

  function logout() {
    // Fire-and-forget server logout
    fetch('/api/auth/logout', {
      method: 'POST',
      headers: getHeaders(),
    }).catch(function () { /* ignore */ });
    _clearToken();
    showLoginPage();
  }

  // ── Password change ──

  async function changePassword(oldPassword, newPassword) {
    const resp = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '密码修改失败');
    }
    return data;
  }

  // ── API wrappers (with auto-auth + 401 handling) ──

  async function fetchGet(url) {
    const headers = getHeaders();
    const resp = await fetch(url, { headers: headers });
    if (resp.status === 401) {
      _clearToken();
      showLoginPage();
      throw new Error('认证已过期，请重新登录');
    }
    return resp;
  }

  async function fetchPost(url, body) {
    const headers = getHeaders();
    const resp = await fetch(url, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body),
    });
    if (resp.status === 401) {
      _clearToken();
      showLoginPage();
      throw new Error('认证已过期，请重新登录');
    }
    return resp;
  }

  // BUG-FIX(2026-09-07)：新增 DELETE 包装，统一 401 → 清 token + 跳登录
  // （原先 agent.js 等处的裸 fetch DELETE 在 token 过期时静默失败，不跳登录）
  async function fetchDelete(url) {
    const headers = getHeaders();
    const resp = await fetch(url, {
      method: 'DELETE',
      headers: headers,
    });
    if (resp.status === 401) {
      _clearToken();
      showLoginPage();
      throw new Error('认证已过期，请重新登录');
    }
    return resp;
  }

  // ── Expose ──
  return {
    init: init,
    isLoggedIn: isLoggedIn,
    getUser: getUser,
    getHeaders: getHeaders,
    login: login,
    logout: logout,
    changePassword: changePassword,
    fetchGet: fetchGet,
    fetchPost: fetchPost,
    fetchDelete: fetchDelete,
  };
})();
