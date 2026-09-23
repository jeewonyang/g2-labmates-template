/**
 * First-run seed for the G2 labmates template.
 *
 * Everything seeded here is about ONE thing: getting your own dashboard set
 * up. No sample research projects, no fake errands. The task list you see on
 * day one IS the setup guide (the same steps as SETUP_GUIDE.md), written for
 * someone who has never used a terminal. Finish the tasks, mark the project
 * Done, and the system is yours.
 *
 * Task titles say what to do; descriptions say exactly how. Optional tiers
 * (AI subscriptions, integrations) are `someday` tasks so Today stays honest
 * about what is actually required (very little).
 */
import { PrismaClient, type Prisma } from "@prisma/client";
import { addDays, startOfDay } from "date-fns";

const db = new PrismaClient();

const today = startOfDay(new Date());
const d = (offset: number) => addDays(today, offset);

async function main() {
  console.log("Resetting data…");
  // Order matters for FK constraints.
  await db.entityLink.deleteMany();
  await db.automationEvent.deleteMany();
  await db.captureAutomation.deleteMany();
  await db.inboxItem.deleteMany();
  await db.review.deleteMany();
  await db.timeEntry.deleteMany();
  await db.task.deleteMany();
  await db.note.deleteMany();
  await db.resource.deleteMany();
  await db.project.deleteMany();
  await db.goal.deleteMany();
  await db.area.deleteMany();
  await db.tag.deleteMany();

  console.log("Seeding tags…");
  const setupTag = await db.tag.create({ data: { name: "setup" } });

  console.log("Seeding areas…");
  const secondBrain = await db.area.create({
    data: {
      title: "Second Brain",
      type: "area",
      health: "healthy",
      pinned: true,
      description:
        "Running and improving this dashboard itself: setup, your knowledge vault, and the AI agents.",
      tags: { connect: [{ id: setupTag.id }] },
    },
  });
  await db.area.create({
    data: {
      title: "Research",
      type: "area",
      health: "healthy",
      pinned: true,
      description:
        "Your research projects. Create one project per line of work (Planner -> Projects); " +
        "each Active project gets its own lab notebook under Research -> Lab notebook.",
    },
  });

  console.log("Seeding projects…");
  const setup = await db.project.create({
    data: {
      title: "Set up my dashboard",
      status: "active",
      priority: "high",
      description:
        "The seeded tasks in this project ARE the setup guide (SETUP_GUIDE.md has the same " +
        "steps). Do the ones scheduled for today first; everything marked Someday is optional. " +
        "When you finish, set this project to Done - the dashboard is yours.",
      areaId: secondBrain.id,
      startDate: today,
      tags: { connect: [{ id: setupTag.id }] },
    },
  });

  console.log("Seeding tasks…");
  const mk = (data: Omit<Prisma.TaskUncheckedCreateInput, "projectId" | "areaId">) =>
    db.task.create({
      data: {
        projectId: setup.id,
        areaId: secondBrain.id,
        context: "computer",
        ...data,
      },
    });

  const highlight = await mk({
    title: "Open the Setup checklist",
    description:
      "In the left menu, click Diagnostics (or press g then s). The Setup checklist checks " +
      "this machine for you: green rows are done, amber rows need something, grey rows are " +
      "optional features you have not turned on.",
    status: "next",
    priority: "high",
    isHighlight: true,
    scheduledDate: today,
  });

  await mk({
    title: "Try capturing a thought",
    description:
      "Press c anywhere in the dashboard, type anything on your mind, and press Enter. It " +
      "lands in the Inbox (Planner -> Inbox), where one click turns it into a task, note, or " +
      "resource. There is one waiting there already. This works with no AI connected.",
    status: "next",
    priority: "medium",
    scheduledDate: today,
  });

  await mk({
    title: "Plan today in the Daily note",
    description:
      "On Today, open the Daily note card on the right. Write your plan as checkboxes " +
      "(- [ ] like this), grouped under @context headings (@lab, @computer, @meetings). " +
      "The 'make tasks' button turns the lines into real tasks after showing you a preview.",
    status: "next",
    priority: "medium",
    scheduledDate: today,
  });

  await mk({
    title: "Link a Claude subscription to turn on the AI agent",
    description:
      "If you have a Claude plan (claude.ai - Pro or Max): install Claude Code from " +
      "claude.com/claude-code, then open a terminal in this folder, type claude and press " +
      "Enter, and follow the sign-in link. No API key needed. Without this, everything " +
      "stays manual.",
    status: "scheduled",
    priority: "high",
    scheduledDate: d(1),
  });

  await mk({
    title: "Run the onboarding interview (after linking Claude)",
    description:
      "In a terminal in this folder, type claude and press Enter, then type: " +
      "'Run the onboarding in VAULT/Memory/BOOTSTRAP.md'. The agent interviews you (who you " +
      "are, your projects, your collaborators, which folders on your computer hold your " +
      "work) and fills in your memory vault. Budget 15-20 minutes.",
    status: "scheduled",
    priority: "high",
    scheduledDate: d(1),
  });

  await mk({
    title: "Build your knowledge base from your own folders",
    description:
      "After onboarding, ask the agent in a claude session: 'Walk me through step 6 of " +
      "SETUP_GUIDE.md: build my knowledge base from my folders.' It maps the folders you " +
      "name into the vault and proposes where each kind of file belongs. Nothing is moved " +
      "or deleted without your approval.",
    status: "scheduled",
    priority: "medium",
    scheduledDate: d(2),
  });

  await mk({
    title: "Create your first research project and lab notebook",
    description:
      "Research -> Lab notebook -> New entry -> '+ New project…'. That creates an Active " +
      "planner project and its notebook folder in one step. Then log one past experiment by " +
      "hand to see the format (input data path and result data path are required).",
    status: "scheduled",
    priority: "medium",
    scheduledDate: d(2),
  });

  await mk({
    title: "Try the LabSerf bench on one of your datasets",
    description:
      "Needs Python with the packages in labserf/requirements.txt " +
      "(see SETUP_GUIDE.md step 7). Then Research -> Lab notebook -> Launch: pick flow " +
      "cytometry or ultrasound, paste the folder that holds your data, and run. Raw data is " +
      "only read; results land in an AI_analysis folder beside it and a notebook entry is filed.",
    status: "someday",
    priority: "medium",
  });

  await mk({
    title: "Add a ChatGPT subscription or Ollama (optional)",
    description:
      "A paid ChatGPT plan adds a second runtime (install the Codex CLI from " +
      "chatgpt.com/codex, then run: codex login). Ollama (ollama.com, free) runs small models " +
      "on your own computer so private notes can be sorted without leaving it; after " +
      "installing, run: ollama pull bge-m3. Skip freely.",
    status: "someday",
    priority: "low",
  });

  await mk({
    title: "Connect Gmail, Calendar, Slack, or GitHub (optional)",
    description:
      "In a claude session, paste: 'Walk me through connecting my Google account using " +
      "docs/INTEGRATIONS_SETUP.md. I have no coding experience.' The agent drafts emails and " +
      "proposes calendar events, but only you send or approve anything.",
    status: "someday",
    priority: "low",
  });

  await db.project.update({
    where: { id: setup.id },
    data: { nextActionId: highlight.id },
  });

  console.log("Seeding notes…");
  await db.note.create({
    data: {
      title: "Welcome - how this dashboard works",
      type: "permanent",
      pinned: true,
      contentMarkdown:
        "# Welcome\n\n" +
        "This is your personal research dashboard. It has two halves:\n\n" +
        "- **The dashboard**: capture anything with `c`, sort it from the Inbox into tasks, " +
        "notes, and resources, plan your day on **Today**, keep a **lab notebook** per " +
        "project, and reflect in Reviews. **This half needs no AI.**\n" +
        "- **The agent layer** (optional): once you link a Claude subscription, agents work " +
        "alongside you - reviewing papers for the Research library, running LabSerf analyses " +
        "on your data, sorting captures, and keeping a memory vault about your work. One hard " +
        "rule: **it drafts and proposes, you approve.** It never emails, posts, or deletes " +
        "anything on its own.\n\n" +
        "Start with the **Set up my dashboard** project. `SETUP_GUIDE.md` in this folder has " +
        "the same steps with more detail.",
      areaId: secondBrain.id,
      projectId: setup.id,
      tags: { connect: [{ id: setupTag.id }] },
    },
  });

  console.log("Seeding inbox / captured items…");
  await db.inboxItem.create({
    data: {
      rawText:
        "Try triaging me! Use the buttons on this row to turn me into a task, a note, or a " +
        "resource - or archive me. This is the manual loop the whole system is built on.",
      parsedTitle: "Try triaging me",
      type: "idea",
      source: "manual",
      tags: { connect: [{ id: setupTag.id }] },
    },
  });

  console.log("Seed complete.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await db.$disconnect();
  });
