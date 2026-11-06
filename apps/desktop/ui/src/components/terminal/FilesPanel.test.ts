// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The files of an SSH session (R-1072): the panel opens at the login directory, goes into
// folders and back up, downloads a file on a click, uploads from the dialog and from files
// dropped on the window (only into the session shown), replaces a file that exists only after a
// question with the same number, shows progress and errors, and on Windows points a refused
// login to a key or the agent. Names a host sends are shown as text without control characters.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import type { SftpDrop, SftpListing, SftpTransfer, SftpUploaded } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { IpcError } from '$lib/utils/errors';

type Progress = (step: SftpTransfer) => void;

const h = vi.hoisted(() => ({
  sftpList: vi.fn<(session: number, path: string) => Promise<SftpListing>>(),
  sftpMkdir: vi.fn<(session: number, path: string) => Promise<void>>(async () => {}),
  sftpUpload:
    vi.fn<(session: number, dir: string, onProgress: Progress) => Promise<SftpUploaded | null>>(),
  sftpUploadDropped:
    vi.fn<
      (
        session: number,
        dir: string,
        drop: number,
        overwrite: boolean,
        onProgress: Progress,
      ) => Promise<SftpUploaded>
    >(),
  sftpDownload: vi.fn<(session: number, path: string, onProgress: Progress) => Promise<boolean>>(),
  confirm: vi.fn<(message: string) => Promise<boolean>>(async () => true),
  drop: null as ((event: { payload: SftpDrop }) => void) | null,
  unlisten: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({
  sftpList: h.sftpList,
  sftpMkdir: h.sftpMkdir,
  sftpUpload: h.sftpUpload,
  sftpUploadDropped: h.sftpUploadDropped,
  sftpDownload: h.sftpDownload,
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async (event: string, handler: (event: { payload: SftpDrop }) => void) => {
    if (event === 'sftp-drop') h.drop = handler;
    return h.unlisten;
  }),
}));
vi.mock('../ui/ConfirmDialog.svelte', () => ({ confirmDialog: h.confirm }));

import FilesPanel from './FilesPanel.svelte';

const HOME = '/home/ops';
const ID = 7;

function listing(path: string): SftpListing {
  if (path === `${HOME}/www`) {
    return {
      path,
      entries: [
        { name: '..', kind: 'dir', size: 0 },
        { name: 'index.html', kind: 'file', size: 2048 },
      ],
    };
  }
  if (path === `${HOME}/www/..` || path === '.' || path === HOME) {
    return {
      path: HOME,
      entries: [
        { name: '..', kind: 'dir', size: 0 },
        { name: 'www', kind: 'dir', size: 4096 },
        { name: 'notes.txt', kind: 'file', size: 512 },
        { name: 'current', kind: 'link', size: 7 },
      ],
    };
  }
  return { path, entries: [] };
}

function uploaded(over: Partial<SftpUploaded> = {}): SftpUploaded {
  return { drop: 3, uploaded: 1, existing: [], ...over };
}

async function mount(props: { session?: number | null; running?: boolean; shown?: boolean } = {}) {
  const view = render(FilesPanel, { session: ID, running: true, shown: true, ...props });
  if (props.running !== false && props.session !== null) {
    await screen.findByText('notes.txt');
    await idle();
  }
  return view;
}

function entry(name: string): HTMLButtonElement {
  const list = screen.getByRole('list', { name: tNow('terminal.files.list') });
  return within(list).getByText(name).closest('button') as HTMLButtonElement;
}

function button(key: string): HTMLButtonElement {
  return screen.getByRole('button', { name: tNow(key) }) as HTMLButtonElement;
}

// The panel takes the next action once the last one has ended.
async function idle(): Promise<void> {
  await vi.waitFor(() => expect(button('terminal.files.refresh').disabled).toBe(false));
}

let userAgent: ReturnType<typeof vi.spyOn> | null = null;

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  h.drop = null;
  h.sftpList.mockImplementation(async (_session, path) => listing(path));
  h.sftpUpload.mockResolvedValue(uploaded());
  h.sftpUploadDropped.mockResolvedValue(uploaded());
  h.sftpDownload.mockResolvedValue(true);
  h.confirm.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  userAgent?.mockRestore();
  userAgent = null;
});

describe('FilesPanel', () => {
  it('opens at the login directory and goes into a folder and back up', async () => {
    await mount();
    expect(h.sftpList).toHaveBeenCalledWith(ID, '.');
    expect(screen.getByText(HOME)).toBeTruthy();
    // Files show their size, folders and links none.
    expect(entry('notes.txt').textContent).toContain('512 B');
    expect(entry('www').textContent).not.toContain('KB');
    expect(entry('current').textContent).not.toContain(' B');

    await fireEvent.click(entry('www'));
    await screen.findByText('index.html');
    expect(h.sftpList).toHaveBeenLastCalledWith(ID, `${HOME}/www`);
    expect(entry('index.html').textContent).toContain('2 KB');

    await fireEvent.click(entry('..'));
    await screen.findByText('notes.txt');
    expect(h.sftpList).toHaveBeenLastCalledWith(ID, `${HOME}/www/..`);
    expect(screen.getByText(HOME)).toBeTruthy();
    expect(h.sftpDownload).not.toHaveBeenCalled();
  });

  it('downloads a file or a link on a click and shows the progress meanwhile', async () => {
    await mount();
    let step: Progress = () => {};
    let finish: (saved: boolean) => void = () => {};
    h.sftpDownload.mockImplementationOnce(
      (_session, _path, onProgress) =>
        new Promise((resolve) => {
          step = onProgress;
          finish = resolve;
        }),
    );

    await fireEvent.click(entry('notes.txt'));
    expect(h.sftpDownload).toHaveBeenCalledWith(ID, `${HOME}/notes.txt`, expect.any(Function));
    step({ name: 'notes.txt', done: 256, total: 512 });
    const shown = await screen.findByRole('status');
    expect(shown.textContent).toContain('notes.txt: 256 B of 512 B');
    // One action at a time.
    expect(entry('www').disabled).toBe(true);
    expect(button('terminal.files.upload').disabled).toBe(true);

    finish(true);
    await vi.waitFor(() => expect(screen.queryByRole('status')).toBeNull());
    expect(entry('www').disabled).toBe(false);

    await fireEvent.click(entry('current'));
    await vi.waitFor(() =>
      expect(h.sftpDownload).toHaveBeenLastCalledWith(ID, `${HOME}/current`, expect.any(Function)),
    );
  });

  it('uploads from the dialog and replaces what exists only after the question', async () => {
    await mount();
    h.sftpUpload.mockResolvedValueOnce(uploaded({ drop: 4, existing: ['a.txt', 'b.txt'] }));

    await fireEvent.click(button('terminal.files.upload'));
    await vi.waitFor(() =>
      expect(h.sftpUploadDropped).toHaveBeenCalledWith(ID, HOME, 4, true, expect.any(Function)),
    );
    expect(h.sftpUpload).toHaveBeenCalledWith(ID, HOME, expect.any(Function));
    expect(h.confirm.mock.calls[0][0]).toBe(
      tNow('terminal.files.confirmOverwrite', { names: 'a.txt, b.txt' }),
    );
    // The folder is read again.
    await vi.waitFor(() => expect(h.sftpList).toHaveBeenCalledTimes(2));
    await idle();

    // Refused: nothing is replaced.
    h.confirm.mockResolvedValueOnce(false);
    h.sftpUpload.mockResolvedValueOnce(uploaded({ drop: 5, existing: ['a.txt'] }));
    await fireEvent.click(button('terminal.files.upload'));
    await vi.waitFor(() => expect(h.sftpList).toHaveBeenCalledTimes(3));
    expect(h.sftpUploadDropped).toHaveBeenCalledTimes(1);
    await idle();

    // Nothing there: no question.
    h.confirm.mockClear();
    await fireEvent.click(button('terminal.files.upload'));
    await vi.waitFor(() => expect(h.sftpList).toHaveBeenCalledTimes(4));
    expect(h.confirm).not.toHaveBeenCalled();
    await idle();

    // The dialog cancelled: nothing more happens.
    h.sftpUpload.mockResolvedValueOnce(null);
    await fireEvent.click(button('terminal.files.upload'));
    await vi.waitFor(() => expect(h.sftpUpload).toHaveBeenCalledTimes(4));
    await vi.waitFor(() => expect(button('terminal.files.upload').disabled).toBe(false));
    expect(h.sftpList).toHaveBeenCalledTimes(4);
  });

  it('uploads dropped files into the folder shown, only for the session shown', async () => {
    const view = await mount();
    await vi.waitFor(() => expect(h.drop).not.toBeNull());
    await fireEvent.click(entry('www'));
    await screen.findByText('index.html');
    await idle();

    h.sftpUploadDropped.mockResolvedValueOnce(uploaded({ drop: 9, existing: ['index.html'] }));
    h.drop!({ payload: { drop: 9, names: ['index.html', 'new.css'] } });
    await vi.waitFor(() => expect(h.sftpUploadDropped).toHaveBeenCalledTimes(2));
    expect(h.sftpUploadDropped.mock.calls[0].slice(0, 4)).toEqual([ID, `${HOME}/www`, 9, false]);
    expect(h.sftpUploadDropped.mock.calls[1].slice(0, 4)).toEqual([ID, `${HOME}/www`, 9, true]);
    await idle();

    // Another tab is shown, or the session ended: the drop is not this panel's.
    await view.rerender({ session: ID, running: true, shown: false });
    h.drop!({ payload: { drop: 10, names: ['x'] } });
    await view.rerender({ session: ID, running: false, shown: true });
    h.drop!({ payload: { drop: 11, names: ['x'] } });
    await Promise.resolve();
    expect(h.sftpUploadDropped).toHaveBeenCalledTimes(2);
    // Neither was taken as a drop while busy.
    expect(screen.queryByRole('alert')).toBeNull();

    view.unmount();
    expect(h.unlisten).toHaveBeenCalled();
  });

  it('says so when a drop comes while an action runs', async () => {
    await mount();
    await vi.waitFor(() => expect(h.drop).not.toBeNull());
    let finish: (saved: boolean) => void = () => {};
    h.sftpDownload.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    await fireEvent.click(entry('notes.txt'));

    h.drop!({ payload: { drop: 2, names: ['x'] } });
    expect((await screen.findByRole('alert')).textContent).toBe(tNow('terminal.files.busy'));
    expect(h.sftpUploadDropped).not.toHaveBeenCalled();
    finish(true);
  });

  it('creates a folder with a plain name in the folder shown', async () => {
    await mount();
    await fireEvent.click(button('terminal.files.newFolder'));
    const name = screen.getByLabelText(tNow('terminal.files.folderName'));
    const create = button('terminal.files.create');
    expect(create.disabled).toBe(true);
    for (const bad of ['a/b', '..', '.', '  ']) {
      await fireEvent.input(name, { target: { value: bad } });
      expect(create.disabled).toBe(true);
    }

    await fireEvent.input(name, { target: { value: ' backup ' } });
    expect(create.disabled).toBe(false);
    await fireEvent.click(create);
    await vi.waitFor(() => expect(h.sftpMkdir).toHaveBeenCalledWith(ID, `${HOME}/backup`));
    await vi.waitFor(() =>
      expect(screen.queryByLabelText(tNow('terminal.files.folderName'))).toBeNull(),
    );
    expect(h.sftpList).toHaveBeenLastCalledWith(ID, HOME);
  });

  it('shows an error in the panel and points a refused login on Windows to a key', async () => {
    const refused = () => new IpcError('Permission denied (publickey).', 'ERR_CONNECTION');
    h.sftpList.mockRejectedValueOnce(refused());
    const view = render(FilesPanel, { session: ID, running: true, shown: true });
    expect((await screen.findByRole('alert')).textContent).toBe('Permission denied (publickey).');
    expect(screen.queryByText(tNow('terminal.files.windowsKey'))).toBeNull();
    view.unmount();

    userAgent = vi
      .spyOn(navigator, 'userAgent', 'get')
      .mockReturnValue('Mozilla/5.0 (Windows NT 10.0; Win64; x64)');
    h.sftpList.mockRejectedValueOnce(refused());
    render(FilesPanel, { session: ID, running: true, shown: true });
    expect(await screen.findByText(tNow('terminal.files.windowsKey'))).toBeTruthy();

    // Not a refused connection: no hint. A good answer clears the error.
    await idle();
    h.sftpList.mockRejectedValueOnce(new IpcError('bad path', 'ERR_VALIDATION'));
    await fireEvent.click(button('terminal.files.refresh'));
    await vi.waitFor(() => expect(screen.getByRole('alert').textContent).toBe('bad path'));
    expect(screen.queryByText(tNow('terminal.files.windowsKey'))).toBeNull();
    await idle();
    await fireEvent.click(button('terminal.files.refresh'));
    await screen.findByText('notes.txt');
    expect(screen.queryByRole('alert')).toBeNull();

    // Once the channel got through, what the host refuses is no login: no hint.
    await idle();
    h.sftpList.mockRejectedValueOnce(new IpcError('Permission denied', 'ERR_CONNECTION'));
    await fireEvent.click(button('terminal.files.refresh'));
    expect((await screen.findByRole('alert')).textContent).toBe('Permission denied');
    expect(screen.queryByText(tNow('terminal.files.windowsKey'))).toBeNull();
  });

  it('waits for the session to run and reads the folder again once it does', async () => {
    const view = await mount({ session: null, running: false });
    expect(screen.getByText(tNow('terminal.files.notRunning'))).toBeTruthy();
    expect(button('terminal.files.upload').disabled).toBe(true);
    expect(h.sftpList).not.toHaveBeenCalled();

    await view.rerender({ session: ID, running: true, shown: true });
    await screen.findByText('notes.txt');
    expect(screen.queryByText(tNow('terminal.files.notRunning'))).toBeNull();

    // A reconnect starts a new session in Rust: the folder shown is read through it.
    await view.rerender({ session: ID + 1, running: true, shown: true });
    await vi.waitFor(() => expect(h.sftpList).toHaveBeenLastCalledWith(ID + 1, HOME));
  });

  it('shows the names a host sends as text without control characters', async () => {
    const name = 'a\u202etxt.exe\u001b[31m\u061c';
    h.sftpList.mockImplementation(async (_session, path) => ({
      path: HOME,
      entries: [
        ...listing(path).entries,
        { name: '<img src=x onerror=alert(1)>', kind: 'file', size: 1 },
        { name, kind: 'file', size: 1 },
      ],
    }));
    await mount();
    const list = screen.getByRole('list', { name: tNow('terminal.files.list') });
    expect(list.querySelector('img')).toBeNull();
    expect(within(list).getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
    const shown = within(list).getByText('a\ufffdtxt.exe\ufffd[31m\ufffd');
    await fireEvent.click(shown.closest('button')!);
    // The host gets the name as it is.
    await vi.waitFor(() =>
      expect(h.sftpDownload).toHaveBeenCalledWith(ID, `${HOME}/${name}`, expect.any(Function)),
    );
  });
});
