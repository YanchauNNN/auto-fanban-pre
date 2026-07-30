let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function getSessionAccessToken() {
  return accessToken;
}

export function setSessionAccessToken(token: string | null) {
  accessToken = token;
}

export function setSessionUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

export function notifySessionUnauthorized() {
  unauthorizedHandler?.();
}
