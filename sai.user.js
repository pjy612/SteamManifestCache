// ==UserScript==
// @name         SAI 辅助入库脚本
// @namespace    http://tampermonkey.net/
// @version      0.4
// @description  SteamDB & Steam Store & SteamUI 添加 SAI一键入库,配合 v1.0.7.1 及以上食用
// @author       pjy612
// @match        *://steamdb.info/app/*
// @match        *://store.steampowered.com/app/*
// @match        *://steamui.com/*
// @match        *://*.steamui.com/*
// @run-at       document-end
// @grant        none
// @updateURL    https://raw.githubusercontent.com/pjy612/SteamManifestCache/data/sai.user.js
// ==/UserScript==

(function() {
    'use strict';
    function addSteamDbButton(appId) {
        const navLinks = document.querySelector('nav.app-links a');
        if (!navLinks) return;
        const link = document.createElement('a');
        link.innerText = 'SAI入库';
        link.href = `sai://app/${appId}`;
        navLinks.parentNode.insertBefore(link,navLinks);
    }
    function addSteamButton(appId) {
        const navLinks = document.querySelector('div.apphub_OtherSiteInfo');
        if (!navLinks) return;
        const link = document.createElement('a');
        link.className = 'btnv6_blue_hoverfade btn_medium';
        link.innerHTML = '<span>SAI入库</span>';
        link.href = `sai://app/${appId}`;
        navLinks.appendChild(link);
    }
    function addSteamUI(){
        for(let g of document.querySelectorAll(".game-item")){
            let app = g.querySelector("button.appid");
            let db = g.querySelector(".btn.btn-steamdb");
            if(app && db){
                let appId = app.innerText;
                if(!db.classList.contains("ms-2"))db.classList.add("ms-2");
                const pre = db.previousElementSibling;
                if(!pre || pre.name !="sai"){
                    const newLink = document.createElement('a');
                    newLink.name = "sai";
                    newLink.className = 'btn btn-custom ms-2';
                    newLink.href = `sai://app/${appId}`;
                    newLink.target = '_blank';
                    newLink.setAttribute('data-bs-toggle', 'tooltip');
                    newLink.title = 'SAI入库';
                    newLink.innerText = 'SAI入库';
                    db.parentNode.insertBefore(newLink, db);
                }
            }
        }
    }
    function observePage(appId) {
        const observer = new MutationObserver((mutations, obs) => {
            const navLinks = document.querySelector('nav.app-links');
            if (navLinks) {
                addSteamDbButton(appId);
                obs.disconnect(); // 元素出现后停止观察
            }
            const navLinks2 = document.querySelector('div.apphub_OtherSiteInfo');
            if (navLinks2) {
                addSteamButton(appId);
                obs.disconnect(); // 元素出现后停止观察
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        const navLinks = document.querySelector('nav.app-links');
        if (navLinks) {
            addSteamDbButton(appId);
            observer.disconnect(); // 元素出现后停止观察
        }
        const navLinks2 = document.querySelector('div.apphub_OtherSiteInfo');
        if (navLinks2) {
            addSteamButton(appId);
            observer.disconnect(); // 元素出现后停止观察
        }
    }
    function observeUI(){
        const observer = new MutationObserver((mutations, obs) => {
            const gameItem = document.querySelector(".game-item");
            if(gameItem){
                addSteamUI();
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
    function getAppId() {
        const url = window.location.href;
        const appIdMatch = url.match(/\/app\/(\d+)/);
        return appIdMatch ? appIdMatch[1] : null;
    }
    const appId = getAppId();
    if (appId) {
        observePage(appId);
    }else{
        observeUI();
    }
})();
