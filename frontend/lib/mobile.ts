/** True only for Android phones/tablets and iOS (iPhone / iPad / iPod). */
export function isAndroidOrIOS(ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''): boolean {
  if (!ua) return false;
  if (/Android/i.test(ua)) return true;
  if (/iPhone|iPod/i.test(ua)) return true;
  // iPadOS 13+ can report as Macintosh — treat touch Macs as iPad
  if (/iPad/i.test(ua)) return true;
  if (
    typeof navigator !== 'undefined' &&
    /Macintosh/i.test(ua) &&
    Number(navigator.maxTouchPoints) > 1
  ) {
    return true;
  }
  return false;
}
