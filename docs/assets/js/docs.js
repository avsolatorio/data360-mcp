function initConnectTabs() {
  const tabs = document.querySelectorAll("[data-connect-tab]");
  const panels = document.querySelectorAll("[data-connect-panel]");

  if (tabs.length === 0 || panels.length === 0) {
    return;
  }

  function activateTab(tabId) {
    for (const tab of tabs) {
      const isActive = tab.dataset.connectTab === tabId;
      tab.classList.toggle("connect-tab--active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    }

    for (const panel of panels) {
      const isActive = panel.dataset.connectPanel === tabId;
      panel.hidden = !isActive;
    }
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      activateTab(tab.dataset.connectTab);
    });
  }

  activateTab("cursor");
}

const QUESTION_TOOL_FLOWS = {
  1: [
    {
      tool: "data360_find_codelist_value",
      detail: 'dimension="REF_AREA", query="Kenya" → KEN',
    },
    {
      tool: "data360_search_indicators",
      detail:
        'query="GDP per capita", required_country="Kenya" → WDI series with Kenya coverage',
    },
    {
      tool: "data360_get_disaggregation",
      detail:
        "database_id, indicator_id → confirm years 2004–2024 and available dimensions",
    },
    {
      tool: "data360_get_data",
      detail:
        'country_code="KEN", start_year=2004, end_year=2024 → time series for the answer',
    },
  ],
  2: [
    {
      tool: "data360_find_codelist_value",
      detail: 'dimension="REF_AREA", query="Bangladesh" → BGD',
    },
    {
      tool: "data360_search_indicators",
      detail:
        'query="female labor force participation", database="WDI", required_country="Bangladesh"',
    },
    {
      tool: "data360_get_disaggregation",
      detail:
        "top matches → verify Bangladesh appears in coverage for each candidate series",
    },
    {
      tool: "data360_get_metadata",
      detail:
        "selected indicator → definition and source to cite in the response",
    },
  ],
  3: [
    {
      tool: "data360_search_indicators",
      detail:
        'query="PPP adjusted GDP per capita" → pick the official WDI / macro series',
    },
    {
      tool: "data360_get_metadata",
      detail:
        "definition_long, source, methodology, aggregation_method, limitation",
    },
  ],
  4: [
    {
      tool: "data360_find_codelist_value",
      detail:
        'dimension="REF_AREA", resolve each country name → ISO3 codes (e.g. KEN, IND, NGA)',
    },
    {
      tool: "data360_search_indicators",
      detail: 'query="access to electricity" → select the best-matching indicator',
    },
    {
      tool: "data360_get_disaggregation",
      detail:
        "confirm electricity series spans 2010–present for all three countries",
    },
    {
      tool: "data360_get_viz_spec",
      detail:
        'chart_type="line", country_code=[…], start_year=2010 → Vega-Lite spec + chart URL',
    },
  ],
};

const FLOW_STEP_DELAY_MS = 420;

const AUDIENCE_DETAILS = {
  1: [
    {
      title: "MCP clients",
      detail:
        "Cursor, Claude Desktop, VS Code, or a LangGraph agent wired to the hosted MCP URL.",
    },
    {
      title: "Bootstrap resources",
      detail:
        "Load data360://context and data360://agent-recipe before calling tools.",
    },
    {
      title: "Core workflow",
      detail:
        "search_indicators → get_disaggregation → get_data or get_viz_spec.",
    },
    {
      title: "Examples in repo",
      detail:
        "langchain-minimal, langchain-graph, and demo_web for local testing.",
    },
  ],
  2: [
    {
      title: "Verified answers",
      detail:
        "Every value and definition comes from Data360—not from model memory.",
    },
    {
      title: "Citation-ready metadata",
      detail:
        "get_metadata for source, methodology, limitations, and statistical concepts.",
    },
    {
      title: "Coverage checks",
      detail:
        "required_country filters and get_disaggregation before drawing conclusions.",
    },
    {
      title: "Compact summaries",
      detail:
        "summarize_data, rank_countries, and compare_countries for report-ready output.",
    },
  ],
  3: [
    {
      title: "Hosted MCP",
      detail:
        "Point production clients at the public MCP endpoint (APIM) with subscription key when required.",
    },
    {
      title: "Embed charts",
      detail:
        "@data360/mcp-ui and @data360/mcp-ui-angular for Vega chart cards in your UI.",
    },
    {
      title: "Agent graphs",
      detail:
        "data360-mcp-agent LangGraph nodes with optional gating and streaming events.",
    },
    {
      title: "Operations",
      detail: "GET /health and GET /ready for load balancers and uptime monitors.",
    },
  ],
};

function initExpandCardList(config) {
  const triggers = document.querySelectorAll(config.triggerSelector);

  if (triggers.length === 0) {
    return;
  }

  let activeTrigger = null;
  let animationToken = 0;

  function closePanel(trigger) {
    const item = trigger.closest(config.itemSelector);
    const panel = document.getElementById(trigger.getAttribute("aria-controls"));

    trigger.setAttribute("aria-expanded", "false");
    item?.classList.remove(config.openClass);

    if (panel) {
      panel.hidden = true;
      const stepsList = panel.querySelector(".question-flow__steps");
      stepsList?.replaceChildren();
    }
  }

  function animateSteps(stepElements, token) {
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const delay = reducedMotion ? 0 : FLOW_STEP_DELAY_MS;

    for (const [index, stepElement] of stepElements.entries()) {
      window.setTimeout(() => {
        if (token !== animationToken) {
          return;
        }
        stepElement.classList.add("is-visible");
      }, index * delay);
    }
  }

  function openPanel(trigger) {
    const contentId = trigger.dataset[config.idDatasetKey];
    const panel = document.getElementById(trigger.getAttribute("aria-controls"));
    const item = trigger.closest(config.itemSelector);
    const steps = config.contentMap[contentId];
    const stepsList = panel?.querySelector(".question-flow__steps");

    if (!panel || !contentId || !steps || !stepsList) {
      return;
    }

    animationToken += 1;
    const token = animationToken;

    trigger.setAttribute("aria-expanded", "true");
    item?.classList.add(config.openClass);
    panel.hidden = false;
    stepsList.replaceChildren();

    const stepElements = [];

    for (const [index, step] of steps.entries()) {
      const stepItem = document.createElement("li");
      stepItem.className = "question-flow__step";

      const stepIndex = document.createElement("span");
      stepIndex.className = "question-flow__step-index";
      stepIndex.textContent = String(index + 1);

      const stepBody = document.createElement("span");
      stepBody.className = "question-flow__step-body";
      config.renderStep(step, stepBody);

      stepItem.append(stepIndex, stepBody);
      stepsList.append(stepItem);
      stepElements.push(stepItem);
    }

    animateSteps(stepElements, token);
  }

  for (const trigger of triggers) {
    trigger.addEventListener("click", () => {
      const isOpen = trigger.getAttribute("aria-expanded") === "true";

      if (activeTrigger && activeTrigger !== trigger) {
        closePanel(activeTrigger);
      }

      if (isOpen) {
        closePanel(trigger);
        activeTrigger = null;
        return;
      }

      openPanel(trigger);
      activeTrigger = trigger;
    });
  }
}

function initQuestionFlows() {
  initExpandCardList({
    triggerSelector: ".question-item__trigger",
    itemSelector: ".question-item",
    openClass: "question-item--open",
    idDatasetKey: "questionId",
    contentMap: QUESTION_TOOL_FLOWS,
    renderStep(step, stepBody) {
      const toolName = document.createElement("span");
      toolName.className = "question-flow__tool";
      toolName.textContent = step.tool;

      const detail = document.createElement("span");
      detail.className = "question-flow__detail";
      detail.textContent = step.detail;

      const status = document.createElement("span");
      status.className = "question-flow__status";
      status.textContent = "Complete";

      stepBody.append(toolName, detail, status);
    },
  });
}

function initAudienceCards() {
  initExpandCardList({
    triggerSelector: ".audience-item__trigger",
    itemSelector: ".audience-item",
    openClass: "audience-item--open",
    idDatasetKey: "audienceId",
    contentMap: AUDIENCE_DETAILS,
    renderStep(step, stepBody) {
      const title = document.createElement("span");
      title.className = "question-flow__heading";
      title.textContent = step.title;

      const detail = document.createElement("span");
      detail.className = "question-flow__detail";
      detail.textContent = step.detail;

      stepBody.append(title, detail);
    },
  });
}

function initTocScrollSpy() {
  const links = document.querySelectorAll('.docs-toc__list a[href^="#"]');
  const sections = [];

  for (const link of links) {
    const href = link.getAttribute("href");
    if (!href || href.length < 2) {
      continue;
    }

    const id = href.slice(1);
    const target = getTocSpyTarget(id);
    if (target) {
      sections.push({ id, link, target });
    }
  }

  if (sections.length === 0) {
    return;
  }

  let ticking = false;

  function getHeaderOffset() {
    const rootStyles = getComputedStyle(document.documentElement);
    const offset = Number.parseFloat(rootStyles.getPropertyValue("--scroll-offset"));
    return Number.isFinite(offset) ? offset : 80;
  }

  /** Line below the sticky header; section headings above this line are "passed". */
  function getScrollMarker() {
    const headerOffset = getHeaderOffset();
    const viewportBand = Math.min(window.innerHeight * 0.28, 220);
    return headerOffset + viewportBand;
  }

  function setActiveLink(activeId) {
    for (const { id, link } of sections) {
      const isActive = id === activeId;
      link.classList.toggle("docs-toc__link--active", isActive);
      if (isActive) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    }
  }

  function updateActiveLink() {
    ticking = false;

    const nearBottom =
      window.innerHeight + window.scrollY >=
      document.documentElement.scrollHeight - 48;

    if (nearBottom) {
      setActiveLink(sections.at(-1).id);
      return;
    }

    const marker = getScrollMarker();
    let activeId = sections[0].id;

    for (const { id, target } of sections) {
      if (target.getBoundingClientRect().top <= marker) {
        activeId = id;
      }
    }

    setActiveLink(activeId);
  }

  function scheduleUpdate() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(updateActiveLink);
    }
  }

  window.addEventListener("scroll", scheduleUpdate, { passive: true });
  window.addEventListener("resize", scheduleUpdate, { passive: true });
  updateActiveLink();
}

/** Use section headings as spy targets (not wrapper divs like #technical). */
function getTocSpyTarget(id) {
  const element = document.getElementById(id);
  if (!element) {
    return null;
  }

  if (id === "technical") {
    return document.getElementById("technical-heading") ?? element;
  }

  const heading = element.querySelector(
    ":scope > h2, :scope > h3, :scope > .section__title",
  );
  return heading ?? element;
}

(function () {
  initConnectTabs();
  initQuestionFlows();
  initAudienceCards();
  initTocScrollSpy();
})();
