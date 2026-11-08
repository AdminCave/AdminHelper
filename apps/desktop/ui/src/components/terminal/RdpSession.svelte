<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  One embedded RDP session (R-1098), after the mockup (DesignSystem ui_kits/adminhelper/rdp.jsx):
  above the picture what it is connected to and its actions, the phases over it, below it the
  figures of the stream. The desktop follows the tab (fit) or keeps a fixed size with a zoom and
  scrollbars (R-1100); a resize goes to the session once the tab kept its size for a moment.
  A click into the picture grabs the keyboard, Ctrl+Alt+Home gives it back.
  A certificate the session was refused for is shown to be confirmed; confirmed, it starts anew.
  In a window of its own (R-1101, `onDock`) it shows what that window may do: no start, no
  screenshot, no details, no full screen; the way back is *Dock*.
  *Multi-monitor* shows the session across the first two monitors of the system: the tab the
  first, a window of its own the second (`screen` 1), which shows the picture and takes input
  only, while the tab lays both out. With one monitor the tab is fitted.
-->
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import {
    Cable,
    Camera,
    Gauge,
    Keyboard,
    Minimize,
    MonitorOff,
    Power,
    RotateCw,
    ShieldAlert,
    SquareArrowDownLeft,
    X,
    ZoomIn,
    ZoomOut,
  } from '@lucide/svelte';
  import * as bridge from '$lib/bridge';
  import type {
    RdpDisplay,
    RdpPerformanceProfile,
    RdpScalingMode,
    RdpSessionInfo,
    RdpWindowMode,
    SystemMonitor,
  } from '$lib/bridge/types';
  import { t } from '$lib/i18n';
  import {
    clampZoom,
    debounce,
    fitDisplay,
    fixedDisplay,
    layoutOf,
    monitorDisplay,
    RESIZE_DEBOUNCE_MS,
    ZOOM,
    zoomedSize,
  } from '$lib/rdp/display';
  import { FrameSocket, type FrameInput, type FrameStats } from '$lib/rdp/frameSocket';
  import { buttonsOf, grabKeyboard, toDesktop, wheelOf, type KeyboardGrab } from '$lib/rdp/input';
  import { createRenderer, type Renderer } from '$lib/rdp/renderer';
  import { settings } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import {
    closeRdpMonitor,
    disconnectRdp,
    openRdpMonitor,
    reconnectRdp,
    setRdpDisplay,
    setRdpPerformance,
    setRdpScaling,
    setRdpWindow,
    terminals,
    trustRdpCertificate,
    type TerminalSession,
  } from '$lib/stores/terminals';
  import { tunnelMappings } from '$lib/stores/tunnel';
  import { errMsg } from '$lib/utils/errors';
  import Button from '../ui/Button.svelte';
  import Dot from '../ui/Dot.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Kbd from '../ui/Kbd.svelte';
  import Modal from '../ui/Modal.svelte';
  import Pill from '../ui/Pill.svelte';
  import Select from '../ui/Select.svelte';
  import Spinner from '../ui/Spinner.svelte';

  interface Props {
    session: TerminalSession;
    /** "Close session": the tab closes, after asking when the options say so. */
    onClose?: () => void;
    /** Shown in a window of its own: docks it back into its tab. */
    onDock?: () => void;
    /** 1: the second monitor of a session across two, in a window of its own. */
    screen?: number;
  }

  let { session, onClose, onDock, screen = 0 }: Props = $props();
  let second = $derived(screen === 1);
  let detached = $derived(onDock !== undefined || second);

  let viewport: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let renderer: Renderer | null = null;
  let socket: FrameSocket | null = null;
  let keyboard: KeyboardGrab | null = null;

  let stats = $state<FrameStats | null>(null);
  // What the frames say; reassigned only when it changes, not with every frame.
  let desktop = $state({ width: 0, height: 0 });
  // The CSS size of the picture's box, from the ResizeObserver.
  let box = { width: 0, height: 0 };
  // A fixed desktop is shown at this zoom in percent, or fitted into the tab.
  let zoom = $state<number | 'fit'>(100);
  let grabbed = $state(false);
  // The certificate dialog put aside: the overlay offers it again.
  let certificateLater = $state(false);
  let info = $state<RdpSessionInfo | null>(null);

  let rdp = $derived(session.rdp!);
  let connected = $derived(rdp.phase === 'connected');
  let target = $derived.by(() => {
    const c = session.connection;
    const user = c.username ? `${c.domain ? `${c.domain}\\` : ''}${c.username} @ ` : '';
    const port = c.port && c.port !== 3389 ? `:${c.port}` : '';
    return `${user}${c.host ?? ''}${port}`;
  });
  // As the connection list shows it: the last enabled mapping for the connection.
  let tunnel = $derived(
    $tunnelMappings.filter((m) => m.enabled && m.connectionId === session.connection.id).at(-1)
      ?.name ?? null,
  );
  let statusText = $derived.by(() => {
    if (rdp.phase === 'connected') return $t('terminal.status.connected');
    if (rdp.phase === 'connecting' || rdp.phase === 'reconnecting') {
      return $t('terminal.status.connecting');
    }
    return $t('terminal.status.disconnected');
  });
  let endText = $derived.by(() => {
    if (rdp.phase === 'certificate') return $t('rdp.certificate.pending');
    if (rdp.code && rdp.code !== 'closed') return $t(`rdp.end.${rdp.code}`);
    return rdp.phase === 'failed' ? $t('rdp.end.unknown') : $t('rdp.ended');
  });
  const dash = '—';
  let figures = $derived.by(() => {
    const s = stats;
    return [
      s && s.width > 0 ? `${s.width}×${s.height}` : dash,
      dash,
      s ? `${Math.round(s.fps)} fps` : dash,
      s?.mbps !== undefined ? `${s.mbps.toFixed(1)} Mbit/s` : dash,
      s?.rttMs !== undefined ? `${Math.round(s.rttMs)} ms` : dash,
    ];
  });
  let profile = $derived(
    rdp.performance ?? session.connection.options?.rdp?.performanceProfile ?? 'auto',
  );
  let rdpOptions = $derived(session.connection.options?.rdp);
  let windowMode = $derived<RdpWindowMode>(
    rdp.window ?? rdpOptions?.windowMode ?? $settings?.rdpWindowMode ?? 'fit',
  );
  let layout = $derived(layoutOf(windowMode));
  // Full screen lays the desktop out as fit, over the whole window in full screen.
  let fullscreen = $derived(!detached && windowMode === 'fullscreen');
  let scaling = $derived<RdpScalingMode>(
    rdp.scaling ?? rdpOptions?.scalingMode ?? $settings?.rdpScalingMode ?? 'auto',
  );
  let customSize = $derived(rdpOptions?.customSize ?? $settings?.rdpCustomSize ?? null);
  let layouts = $derived(
    (detached
      ? (['fit', 'custom'] as const)
      : (['fit', 'fullscreen', 'multimon', 'custom'] as const)
    ).map((value) => ({
      value,
      label: $t(`settings.rdp.window.${value}`),
    })),
  );
  let scalings = $derived(
    (['auto', 'normal', 'hdpi'] as const).map((value) => ({
      value,
      label: $t(`settings.rdp.scaling.${value}`),
    })),
  );
  // The CSS size of a zoomed fixed desktop; null while the picture is fitted into the tab.
  let zoomed = $derived.by(() => {
    if (layout !== 'custom' || zoom === 'fit') return null;
    const fixed = fixedDisplay(customSize, scaling, devicePixelRatio);
    const width = desktop.width || fixed.width;
    const height = desktop.height || fixed.height;
    return zoomedSize(width, height, zoom, devicePixelRatio);
  });
  let profiles = $derived(
    (['auto', 'lan', 'broadband', 'low'] as const).map((value) => ({
      value,
      label: $t(`rdp.performance.${value}`),
    })),
  );

  function send(input: FrameInput): void {
    socket?.send(input);
  }

  function wanted(): RdpDisplay | null {
    if (layout === 'custom') return fixedDisplay(customSize, scaling, devicePixelRatio);
    if (box.width <= 0 || box.height <= 0) return null;
    return fitDisplay(box.width, box.height, scaling, devicePixelRatio);
  }

  // The desktop the tab asks for goes to the store for the next start and to the running
  // session; Rust drops what it has already. Across two monitors the next start begins with the
  // first one. The second monitor's window shows what the tab lays out.
  function report(): void {
    if (second) return;
    if (monitors) {
      const [first] = monitors;
      setRdpDisplay(session.key, { width: first.w, height: first.h, scale: first.scale });
      send({ t: 'layout', monitors });
      return;
    }
    const display = wanted();
    if (!display) return;
    setRdpDisplay(session.key, display);
    send({ t: 'size', w: display.width, h: display.height, scale: display.scale });
  }
  const reportLater = debounce(report, RESIZE_DEBOUNCE_MS);

  $effect(() => {
    void [layout, scaling, customSize, monitors];
    untrack(report);
  });

  // Hidden tabs stay mounted: only the shown one may hold the window in full screen.
  let shown = $derived($terminals.active === session.key);

  // The window follows the tab into full screen and back, also when the tab goes or hides. A
  // window that cannot go full screen leaves the tab fitted, or the overlay would hide the error.
  $effect(() => {
    if (!fullscreen || !shown) return;
    bridge.setFullscreen(true).catch((err) => {
      reportError(errMsg(err));
      setRdpWindow(session.key, 'fit');
    });
    return () => {
      bridge.setFullscreen(false).catch((err) => reportError(errMsg(err)));
    };
  });

  // With the keyboard released (Ctrl+Alt+Home), F11 leaves full screen; grabbed, it is the
  // server's.
  function onwindowkeydown(e: KeyboardEvent): void {
    if (!fullscreen || !shown || grabbed || e.code !== 'F11') return;
    e.preventDefault();
    setRdpWindow(session.key, 'fit');
  }

  function zoomBy(step: number): void {
    zoom = clampZoom((zoom === 'fit' ? 100 : zoom) + step);
  }

  // Each on its own: a new phase is a new `rdp`, but the same session keeps its socket, and
  // Rust lets only the first client in.
  let sessionId = $derived(rdp.sessionId);
  let wsPort = $derived(rdp.wsPort);
  let token = $derived(rdp.token);

  // Across two monitors while the session runs, in the tab only. A reconnect keeps both: it
  // comes back with the layout, and a `size` meanwhile would shrink it to one monitor.
  let running = $derived(connected || rdp.phase === 'reconnecting');
  let multi = $derived(!detached && windowMode === 'multimon' && running && sessionId !== null);
  // A new `session` comes with every update of the tab; the window goes with the key only.
  let tabKey = $derived(session.key);
  let systemMonitors = $state<SystemMonitor[] | null>(null);
  let monitors = $derived(
    multi && systemMonitors && systemMonitors.length >= 2
      ? [monitorDisplay(systemMonitors[0], scaling), monitorDisplay(systemMonitors[1], scaling)]
      : null,
  );
  let singleScreen = $derived(multi && systemMonitors !== null && systemMonitors.length < 2);

  // The second monitor's window opens with the mode and goes with it, with the session and with
  // the tab.
  $effect(() => {
    if (!multi || sessionId === null) return;
    const id = sessionId;
    const key = tabKey;
    let gone = false;
    bridge.systemMonitors().then(
      (list) => {
        if (gone) return;
        systemMonitors = list;
        if (list.length >= 2) void openRdpMonitor(key);
      },
      (err: unknown) => {
        if (gone) return;
        reportError(errMsg(err));
        setRdpWindow(key, 'fit');
      },
    );
    return () => {
      gone = true;
      systemMonitors = null;
      void closeRdpMonitor(id);
    };
  });

  // A new session in Rust gets a socket of its own; the one before it goes.
  $effect(() => {
    if (sessionId === null || wsPort === null || token === null) return;
    stats = null;
    const current = new FrameSocket(wsPort, token, {
      frame: (frame) => {
        const { desktopWidth: width, desktopHeight: height } = frame.header;
        if (width !== desktop.width || height !== desktop.height) desktop = { width, height };
        renderer?.draw(frame);
      },
      stats: (s) => (stats = s),
      // What the tab asked for while the session started went nowhere: input before the socket
      // opened is dropped.
      opened: report,
      closed: () => {
        if (socket === current) socket = null;
      },
    });
    socket = current;
    return () => {
      keyboard?.release();
      current.close();
      if (socket === current) socket = null;
    };
  });

  $effect(() => {
    if (rdp.phase !== 'certificate') certificateLater = false;
  });

  function point(e: MouseEvent, wheel = 0): void {
    if (!connected) return;
    const { x, y } = toDesktop(
      e.offsetX,
      e.offsetY,
      canvas.clientWidth,
      canvas.clientHeight,
      desktop.width,
      desktop.height,
    );
    send({ t: 'mouse', x, y, buttons: buttonsOf(e.buttons), wheel });
  }

  function onpointerdown(e: PointerEvent): void {
    if (!connected) return;
    viewport.focus();
    keyboard?.grab();
    point(e);
  }

  function onwheel(e: WheelEvent): void {
    if (!connected) return;
    e.preventDefault();
    point(e, wheelOf(e.deltaY));
  }

  async function screenshot(): Promise<void> {
    if (!rdp.sessionId) return;
    try {
      await bridge.rdpSessionScreenshot(rdp.sessionId);
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function showInfo(): Promise<void> {
    if (!rdp.sessionId) return;
    try {
      info = await bridge.rdpSessionInfo(rdp.sessionId);
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  function trust(): void {
    void trustRdpCertificate(session.key);
  }

  onMount(() => {
    renderer = createRenderer(canvas);
    // A lost WebGL context draws nothing until it is back; then a new renderer takes over, and
    // the picture fills in as the session sends what changes.
    const lost = (e: Event) => e.preventDefault();
    const restored = () => {
      renderer?.destroy();
      renderer = createRenderer(canvas);
    };
    canvas.addEventListener('webglcontextlost', lost);
    canvas.addEventListener('webglcontextrestored', restored);
    keyboard = grabKeyboard(viewport, send, (on) => (grabbed = on));
    // Measured before the session starts, so it starts with the size of the tab.
    box = { width: viewport.clientWidth, height: viewport.clientHeight };
    report();
    const resizer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            box = { width: viewport.clientWidth, height: viewport.clientHeight };
            if (layout === 'fit') reportLater();
          });
    resizer?.observe(viewport);
    return () => {
      resizer?.disconnect();
      reportLater.cancel();
      canvas.removeEventListener('webglcontextlost', lost);
      canvas.removeEventListener('webglcontextrestored', restored);
      keyboard?.destroy();
      keyboard = null;
      renderer?.destroy();
      renderer = null;
    };
  });
</script>

<svelte:window onkeydown={onwindowkeydown} />

<div class="rdp" class:fullscreen>
  {#if fullscreen}
    <!-- Esc belongs to the server: the way back is this bar, shown on hover at the top edge. -->
    <div class="rdp-edge">
      <div class="rdp-float" role="toolbar" aria-label={$t('settings.rdp.window.fullscreen')}>
        <span class="rdp-target">{target}</span>
        <Button
          size="sm"
          variant="secondary"
          iconLeft={Keyboard}
          disabled={!connected}
          onclick={() => send({ t: 'cad' })}
        >
          {$t('rdp.cad')}
        </Button>
        <IconButton
          size="sm"
          icon={Power}
          label={$t('rdp.disconnect')}
          disabled={rdp.sessionId === null}
          onclick={() => disconnectRdp(session.key)}
        />
        <Button
          size="sm"
          variant="secondary"
          iconLeft={Minimize}
          onclick={() => setRdpWindow(session.key, 'fit')}
        >
          {$t('rdp.fullscreen.leave')}
        </Button>
      </div>
    </div>
  {/if}
  <header class="rdp-head">
    <Dot st={session.status} ring label={statusText} />
    <span class="rdp-target">{target}</span>
    {#if tunnel}
      <Pill tone="accent" title={$t('terminal.tunnel')}><Cable size={11} />{tunnel}</Pill>
    {/if}
    <span class="rdp-spacer"></span>
    <Button
      size="sm"
      variant="secondary"
      iconLeft={Keyboard}
      disabled={!connected}
      onclick={() => send({ t: 'cad' })}
    >
      {$t('rdp.cad')}
    </Button>
    {#if !second}
      <span class="rdp-sep" aria-hidden="true"></span>
      {#if !detached}
        <IconButton
          size="sm"
          icon={Camera}
          label={$t('rdp.screenshot')}
          disabled={!connected}
          onclick={() => void screenshot()}
        />
        <IconButton
          size="sm"
          icon={Gauge}
          label={$t('rdp.info')}
          disabled={rdp.sessionId === null}
          onclick={() => void showInfo()}
        />
        <IconButton
          size="sm"
          icon={RotateCw}
          label={$t('terminal.reconnect')}
          onclick={() => void reconnectRdp(session.key)}
        />
      {/if}
      <IconButton
        size="sm"
        icon={Power}
        label={$t('rdp.disconnect')}
        disabled={rdp.sessionId === null}
        onclick={() => disconnectRdp(session.key)}
      />
      {#if onDock}
        <Button size="sm" variant="secondary" iconLeft={SquareArrowDownLeft} onclick={onDock}>
          {$t('terminal.dock')}
        </Button>
      {:else}
        <IconButton size="sm" icon={X} label={$t('terminal.close')} onclick={onClose} />
      {/if}
    {/if}
  </header>

  {#if !second}
    <div class="rdp-bar">
      {#if !detached}
        <!-- A new profile starts the session anew, which only its tab may. -->
        <label class="rdp-label" for="rdp-performance-{session.key}">{$t('rdp.performance')}</label>
        <Select
          id="rdp-performance-{session.key}"
          size="sm"
          value={profile}
          options={profiles}
          onChange={(v) => void setRdpPerformance(session.key, v as RdpPerformanceProfile)}
        />
      {/if}
      <label class="rdp-label" for="rdp-window-{session.key}">{$t('rdp.window')}</label>
      <Select
        id="rdp-window-{session.key}"
        size="sm"
        value={fullscreen
          ? 'fullscreen'
          : !detached && windowMode === 'multimon'
            ? 'multimon'
            : layout}
        options={layouts}
        onChange={(v) => setRdpWindow(session.key, v as RdpWindowMode)}
      />
      <label class="rdp-label" for="rdp-scaling-{session.key}">{$t('rdp.scaling')}</label>
      <Select
        id="rdp-scaling-{session.key}"
        size="sm"
        value={scaling}
        options={scalings}
        onChange={(v) => setRdpScaling(session.key, v as RdpScalingMode)}
      />
      {#if layout === 'custom'}
        <span class="rdp-sep" aria-hidden="true"></span>
        <IconButton
          size="sm"
          icon={ZoomOut}
          label={$t('rdp.zoom.out')}
          disabled={zoom !== 'fit' && zoom <= ZOOM.min}
          onclick={() => zoomBy(-ZOOM.step)}
        />
        <span class="rdp-zoom" aria-live="polite">
          {zoom === 'fit' ? $t('rdp.zoom.fit') : `${zoom} %`}
        </span>
        <IconButton
          size="sm"
          icon={ZoomIn}
          label={$t('rdp.zoom.in')}
          disabled={zoom !== 'fit' && zoom >= ZOOM.max}
          onclick={() => zoomBy(ZOOM.step)}
        />
        <Button size="sm" variant="secondary" onclick={() => (zoom = 100)}>
          {$t('rdp.zoom.actual')}
        </Button>
        <Button size="sm" variant="secondary" onclick={() => (zoom = 'fit')}>
          {$t('rdp.zoom.fit')}
        </Button>
      {/if}
    </div>
  {/if}

  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    class="rdp-view"
    class:grabbed
    class:zoomed={zoomed !== null}
    bind:this={viewport}
    tabindex="0"
    role="application"
    aria-label={$t('rdp.view', { name: session.connection.name })}
  >
    <canvas
      bind:this={canvas}
      class:hidden={!connected}
      style:width={zoomed ? `${zoomed.width}px` : null}
      style:height={zoomed ? `${zoomed.height}px` : null}
      {onpointerdown}
      onpointermove={(e) => point(e)}
      onpointerup={(e) => point(e)}
      {onwheel}
      oncontextmenu={(e) => e.preventDefault()}
    ></canvas>
    {#if rdp.phase === 'connecting' || rdp.phase === 'reconnecting'}
      <div class="rdp-overlay" role="status">
        <Spinner size={26} />
        <span>
          {rdp.phase === 'reconnecting'
            ? $t('rdp.reconnecting')
            : $t('rdp.connecting', { host: session.connection.host ?? '' })}
        </span>
        <span class="rdp-steps">{$t('rdp.connecting.steps')}</span>
      </div>
    {:else if !connected}
      <div class="rdp-overlay" role="status">
        {#if rdp.phase === 'certificate'}
          <ShieldAlert size={30} />
        {:else}
          <MonitorOff size={30} />
        {/if}
        <span>{endText}</span>
        {#if second}
          <!-- The tab decides; this window closes with the session. -->
        {:else if onDock}
          <Button size="sm" iconLeft={SquareArrowDownLeft} onclick={onDock}>
            {$t('terminal.dock')}
          </Button>
        {:else if rdp.phase === 'certificate' && rdp.certificate}
          <Button size="sm" onclick={() => (certificateLater = false)}>
            {$t('rdp.certificate.review')}
          </Button>
        {:else}
          <Button size="sm" iconLeft={RotateCw} onclick={() => void reconnectRdp(session.key)}>
            {$t('terminal.reconnect')}
          </Button>
        {/if}
      </div>
    {/if}
  </div>

  <footer class="rdp-foot">
    <span>{figures.join(' · ')}</span>
    {#if rdp.notice === 'drive_unavailable'}
      <span class="rdp-notice">{$t('rdp.notice.driveUnavailable')}</span>
    {/if}
    {#if singleScreen}
      <span class="rdp-notice">{$t('rdp.notice.singleScreen')}</span>
    {/if}
    <span class="rdp-spacer"></span>
    <span class="rdp-hint">
      <Kbd>{$t('rdp.key.ctrl')}</Kbd><Kbd>{$t('rdp.key.alt')}</Kbd><Kbd>{$t('rdp.key.home')}</Kbd>
      {$t('rdp.releaseKeyboard')}
    </span>
  </footer>

  <!-- Inside the tab: in full screen it lies over everything else of the window. -->
  <Modal
    open={!detached && rdp.phase === 'certificate' && rdp.certificate !== null && !certificateLater}
    title={$t('rdp.certificate.title')}
    onClose={() => (certificateLater = true)}
  >
    {#if rdp.certificate}
      <p>
        {rdp.certificate.reason === 'changed'
          ? $t('rdp.certificate.changed', { host: session.connection.host ?? '' })
          : $t('rdp.certificate.unknown', { host: session.connection.host ?? '' })}
      </p>
      <p class="rdp-label">{$t('rdp.certificate.fingerprint')}</p>
      <code class="rdp-fingerprint">{rdp.certificate.fingerprint}</code>
    {/if}
    {#snippet footer()}
      <Button variant="secondary" onclick={() => (certificateLater = true)}>
        {$t('rdp.certificate.cancel')}
      </Button>
      <Button
        variant={rdp.certificate?.reason === 'changed' ? 'danger' : 'primary'}
        onclick={trust}
      >
        {$t('rdp.certificate.trust')}
      </Button>
    {/snippet}
  </Modal>

  <Modal open={info !== null} title={$t('rdp.info')} onClose={() => (info = null)}>
    {#if info}
      <dl class="rdp-info">
        <dt>{$t('rdp.info.target')}</dt>
        <dd>{info.target}</dd>
        <dt>{$t('rdp.info.tunnel')}</dt>
        <dd>{info.via_tunnel ? (info.tunnel ?? $t('rdp.info.yes')) : $t('rdp.info.no')}</dd>
        <dt>{$t('rdp.info.nla')}</dt>
        <dd>{info.credssp ? $t('rdp.info.yes') : $t('rdp.info.no')}</dd>
        <dt>{$t('rdp.info.certificate')}</dt>
        <dd>
          {info.certificate === 'pinned' ? $t('rdp.info.pinned') : $t('rdp.info.trustAll')}
        </dd>
        {#if info.fingerprint}
          <dt>{$t('rdp.certificate.fingerprint')}</dt>
          <dd><code class="rdp-fingerprint">{info.fingerprint}</code></dd>
        {/if}
      </dl>
    {/if}
  </Modal>
</div>

<style>
  .rdp {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--bg);
  }
  /* Over the whole window, which is in full screen: the app around the tab is not seen. */
  .rdp.fullscreen {
    position: fixed;
    inset: 0;
    z-index: 1000;
  }
  .rdp.fullscreen .rdp-head,
  .rdp.fullscreen .rdp-bar,
  .rdp.fullscreen .rdp-foot {
    display: none;
  }
  .rdp-edge {
    position: absolute;
    top: 0;
    left: 50%;
    z-index: 1;
    transform: translateX(-50%);
    padding-bottom: 12px;
  }
  .rdp-float {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius-md) var(--radius-md);
    background: var(--bg-subtle);
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.35);
    transform: translateY(calc(-100% + 4px));
    transition: transform 0.15s ease;
  }
  .rdp-edge:hover .rdp-float,
  .rdp-float:focus-within {
    transform: none;
  }
  .rdp-head {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 46px;
    padding: 0 10px 0 16px;
    border-bottom: 1px solid var(--border);
    flex: 0 0 auto;
    overflow: hidden;
  }
  .rdp-target {
    font-family: var(--font-mono);
    font-size: 12.5px;
    color: var(--text-strong);
    white-space: nowrap;
  }
  .rdp-spacer {
    flex: 1;
  }
  .rdp-sep {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 4px;
  }
  .rdp-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-subtle);
    flex: 0 0 auto;
  }
  .rdp-label {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .rdp-view {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    background: #0b0f14;
    outline: none;
  }
  .rdp-view.grabbed {
    box-shadow: inset 0 0 0 2px var(--accent);
  }
  /* A zoomed desktop has its own size; larger than the tab, it scrolls. */
  .rdp-view.zoomed {
    overflow: auto;
  }
  .rdp-view.zoomed canvas {
    flex: 0 0 auto;
    margin: auto;
  }
  .rdp-zoom {
    min-width: 64px;
    text-align: center;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-muted);
  }
  /* The canvas has the size of the desktop; the picture keeps its aspect within the box. */
  canvas {
    width: 100%;
    height: 100%;
    object-fit: contain;
    cursor: default;
  }
  canvas.hidden {
    visibility: hidden;
  }
  .rdp-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--text-muted);
    font-size: 13px;
    text-align: center;
  }
  .rdp-steps {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-subtle);
  }
  .rdp-foot {
    display: flex;
    gap: 16px;
    align-items: center;
    height: 26px;
    padding: 0 16px;
    border-top: 1px solid var(--border);
    background: var(--bg-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
    flex: 0 0 auto;
    overflow: hidden;
    white-space: nowrap;
  }
  .rdp-notice {
    color: var(--warning);
  }
  .rdp-hint {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .rdp-fingerprint {
    display: block;
    font-family: var(--font-mono);
    font-size: 12px;
    word-break: break-all;
    color: var(--text-strong);
  }
  .rdp-info {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 16px;
    font-size: 13px;
  }
  .rdp-info dt {
    color: var(--text-muted);
  }
  .rdp-info dd {
    margin: 0;
  }
</style>
