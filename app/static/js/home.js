/* =========================================================
   StreamVault — home.js
   Melhorias visuais e interativas da homepage Netflix-style
   ========================================================= */

(() => {
    "use strict";

    /* -------- Navbar scroll effect -------- */
    const navbar = document.getElementById("svNavbar");
    if (navbar) {
        let lastScrollTop = 0;
        window.addEventListener("scroll", () => {
            const scrollTop = window.scrollY;
            if (scrollTop > 100) {
                navbar.classList.add("scrolled");
            } else {
                navbar.classList.remove("scrolled");
            }
            lastScrollTop = scrollTop;
        }, false);
    }

    /* -------- Carousel smooth scroll -------- */
    function setupCarousels() {
        const carousels = document.querySelectorAll(".sv-carousel");
        
        carousels.forEach(carousel => {
            const row = carousel.querySelector(".sv-row");
            if (!row) return;

            const prevBtn = carousel.querySelector(".sv-carousel-btn.prev");
            const nextBtn = carousel.querySelector(".sv-carousel-btn.next");
            
            if (prevBtn && nextBtn) {
                const scrollAmount = 300;
                
                prevBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    row.scrollBy({
                        left: -scrollAmount,
                        behavior: "smooth"
                    });
                });
                
                nextBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    row.scrollBy({
                        left: scrollAmount,
                        behavior: "smooth"
                    });
                });
            }
        });
    }

    /* -------- Intersection Observer para animações ao scroll -------- */
    function setupIntersectionObserver() {
        const options = {
            threshold: 0.1,
            rootMargin: "0px 0px -100px 0px"
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = "1";
                    entry.target.style.transform = "translateY(0)";
                }
            });
        }, options);

        // Animar seções ao entrar na viewport
        document.querySelectorAll(".sv-section").forEach(section => {
            section.style.opacity = "0";
            section.style.transform = "translateY(20px)";
            section.style.transition = "opacity 0.6s ease, transform 0.6s ease";
            observer.observe(section);
        });
    }

    /* -------- Efeito hover melhorado em cards -------- */
    function setupCardHoverEffects() {
        const cards = document.querySelectorAll(".sv-card");
        
        cards.forEach(card => {
            card.addEventListener("mouseenter", function() {
                // Subtil parallax effect
                const rect = this.getBoundingClientRect();
                const x = (rect.x + rect.width / 2 - window.innerWidth / 2) / 50;
                this.style.transform = `perspective(1000px) rotateY(${x}deg) translateY(-12px) scale(1.05)`;
            });
            
            card.addEventListener("mouseleave", function() {
                this.style.transform = "";
            });
        });
    }

    /* -------- Inicializar ao carregar -------- */
    document.addEventListener("DOMContentLoaded", () => {
        setupCarousels();
        setupIntersectionObserver();
        setupCardHoverEffects();
    });

    /* -------- Fallback para quando o DOM está pronto antes do evento -------- */
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupCarousels);
    } else {
        setupCarousels();
        setupIntersectionObserver();
        setupCardHoverEffects();
    }
})();
