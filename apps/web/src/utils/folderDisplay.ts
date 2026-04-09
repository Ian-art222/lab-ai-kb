/** 将后端目录名 `admin_{id}_{slug}` 转为友好展示名（不改变真实 name，仅展示层）。 */
export function formatAdminPrivateFolderDisplayName(
  raw: string,
  opts: { isAdmin: boolean; isRoot: boolean; userId: number | null },
): string {
  const m = raw.match(/^admin_(\d+)_/)
  if (!m) return raw
  const ownerId = Number(m[1])
  if (opts.isAdmin && opts.userId != null && ownerId === opts.userId) {
    return '我的目录'
  }
  if (opts.isRoot) {
    return `管理员 #${ownerId} 的个人目录`
  }
  return raw
}
