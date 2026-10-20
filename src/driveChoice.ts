// Which drive a download goes to by default, and where its file will end up. Kept apart from the panel so a test can pin it down:
// the first hardware test was surprised that a mounted USB drive wins, so the choice and the path must stay visible and predictable.
export interface DriveLike {
  id: string;
  external: boolean;
  path: string;
}

// Same order as a game's download page: the saved default drive, else an external drive (USB), else the first one.
export function chooseDrive<T extends DriveLike>(drives: T[], preferredId?: string): T | undefined {
  return drives.find((d) => d.id === preferredId) || drives.find((d) => d.external) || drives[0];
}

// The full path of the finished file, or just its folder while the provider has yet to name it.
export function destinationPath(drive: DriveLike | undefined, fileName: string, nameUnknown: boolean): string {
  if (!drive) return "";
  return `${drive.path}/${nameUnknown ? "" : fileName.trim()}`;
}
