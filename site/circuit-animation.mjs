import { gsap } from "gsap";

export function animateCircuit(hero) {
  const button = hero.querySelector(".circuit-toggle");
  const media = gsap.matchMedia();
  media.add(
    "(prefers-reduced-motion: no-preference)",
    () => {
      let userPaused = false;
      let visible = false;
      const timeline = gsap.timeline({ paused: true });
      hero.querySelectorAll(".circuit-pulse").forEach((pulse, index) => {
        timeline.fromTo(
          pulse,
          { attr: { "stroke-dashoffset": 0.05 }, opacity: 0 },
          {
            attr: { "stroke-dashoffset": -1.05 },
            opacity: 0.8,
            duration: 4.5 + (index % 3) * 1.2,
            ease: "none",
            repeat: -1,
            repeatDelay: 1.2 + (index % 2) * 0.8,
          },
          index * 0.65,
        );
      });
      timeline.to(
        hero.querySelectorAll(".silicon-cell-active"),
        {
          opacity: 0.6,
          duration: 2.8,
          stagger: 0.16,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
        },
        0,
      );
      const update = () =>
        timeline.paused(userPaused || !visible || document.hidden);
      const toggle = () => {
        userPaused = !userPaused;
        button.setAttribute("aria-pressed", String(userPaused));
        button.setAttribute(
          "aria-label",
          `${userPaused ? "Resume" : "Pause"} circuit animation`,
        );
        button.lastElementChild.textContent = `${userPaused ? "Resume" : "Pause"} animation`;
        button.firstElementChild.textContent = userPaused ? "▷" : "Ⅱ";
        update();
      };
      const observer = new IntersectionObserver(([entry]) => {
        visible = entry.isIntersecting;
        update();
      });
      observer.observe(hero);
      button.hidden = false;
      button.addEventListener("click", toggle);
      document.addEventListener("visibilitychange", update);
      return () => {
        observer.disconnect();
        button.removeEventListener("click", toggle);
        document.removeEventListener("visibilitychange", update);
        button.hidden = true;
        button.setAttribute("aria-pressed", "false");
        button.setAttribute("aria-label", "Pause circuit animation");
        button.lastElementChild.textContent = "Pause animation";
        button.firstElementChild.textContent = "Ⅱ";
      };
    },
    hero,
  );
  // GSAP's media context reverts every tween when reduced motion is enabled.
  return () => media.revert();
}
