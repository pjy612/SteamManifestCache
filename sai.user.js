// ==UserScript==
// @name         SAI 辅助入库脚本
// @namespace    http://tampermonkey.net/
// @version      0.8
// @description  SteamDB 添加 SAI一键入库,配合 v1.0.7.1 及以上食用
// @author       pjy612
// @match        *://steamdb.info/app/*
// @match        *://steamcommunity.com/*/filedetails/*
// @run-at       document-end
// @grant        none
// @updateURL    https://gitee.com/pjy612/sai/raw/master/sai.user.js
// ==/UserScript==

(function() {
    'use strict';
    function addSteamDbButton(appId) {
        const navLinks = document.querySelector('nav.app-links a');
        if (!navLinks) return;
        const depotsLinks = document.querySelector(".tabnav-tab[aria-controls='depots']");
        if (!depotsLinks) return;
        const link = document.createElement('a');
        link.className = "btn";
        link.innerText = 'SAI入库';
        link.href = `sai://app/${appId}`;
        navLinks.parentNode.insertBefore(link,navLinks);
    }
    function addSteamButton(appId) {
        return;
        const navLinks = document.querySelector('div.apphub_OtherSiteInfo');
        if (!navLinks) return;
        const link = document.createElement('a');
        link.className = 'btnv6_blue_hoverfade btn_medium';
        link.innerHTML = '<span>SAI入库</span>';
        link.href = `sai://app/${appId}`;
        navLinks.appendChild(link);
    }
    function addSteamUI(){
        return;
        for(let g of document.querySelectorAll(".game-card")){
            let appId = g.getAttribute("data-appid");
            let actions = g.querySelector(".game-actions-group");
            let db = g.querySelector(".btn-action.btn-detail");
            if(actions){
                const next = db.nextElementSibling;
                if(!next || next.name !="sai"){
                    const newLink = document.createElement('a');
                    newLink.name = "sai";
                    newLink.className = 'btn-action';
                    newLink.style = 'background-color: #3f792d;color: #f9f9f9;text-decoration-line: none;';
                    newLink.href = `sai://app/${appId}`;
                    newLink.target = '_blank';
                    newLink.title = 'SAI';
                    newLink.innerText = 'SAI';
                    db.parentNode.appendChild(newLink, db);
                }
            }
        }
    }
    function addWrokShopBtn(pubId){
        const navLinks = document.querySelector('#SubscribeItemBtn');
        if (!navLinks) return;
        if(pubId){
            {
                const linkElement = document.createElement('a');
                linkElement.href = `sai://pub/${pubId}`;
                linkElement.target = '_blank';
                linkElement.title = 'SAI入库';
                linkElement.className = 'btn_green_white_innerfade btn_border_2px btn_medium';
                const subscribeText = document.createElement('span');
                subscribeText.style = 'padding-left: 15px;';
                const subscribeOptionAdd = document.createElement('div');
                subscribeOptionAdd.textContent = 'SAI入库';
                subscribeText.appendChild(subscribeOptionAdd);
                linkElement.appendChild(subscribeText);
                navLinks.insertAdjacentElement('afterend', linkElement);
            }
            // {
            //     const linkElement = document.createElement('a');
            //     linkElement.href = `https://caigamer.com/?steam_download?id=${pubId}`;
            //     linkElement.target = '_blank';
            //     linkElement.title = '菜玩入库';
            //     linkElement.className = 'btn_green_white_innerfade btn_border_2px btn_medium';
            //     const subscribeText = document.createElement('span');
            //     subscribeText.style = 'padding-left: 15px;';
            //     const subscribeOptionAdd = document.createElement('div');
            //     subscribeOptionAdd.textContent = '菜玩入库';
            //     subscribeText.appendChild(subscribeOptionAdd);
            //     linkElement.appendChild(subscribeText);
            //     navLinks.insertAdjacentElement('afterend', linkElement);
            // }
        }
    }
    function observeAppPage(appId) {
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
    function observePubPage(pubId) {
        const observer = new MutationObserver((mutations, obs) => {
            const navLinks = document.querySelector('#SubscribeItemBtn');
            if (navLinks) {
                addWrokShopBtn(pubId);
                obs.disconnect(); // 元素出现后停止观察
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        const navLinks = document.querySelector('#SubscribeItemBtn');
        if (navLinks) {
            addWrokShopBtn(pubId);
            observer.disconnect(); // 元素出现后停止观察
        }
    }
    function observeUI(){
        const observer = new MutationObserver((mutations, obs) => {
            const gameItem = document.querySelector(".game-card");
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
    function getPubId() {
        const url = window.location.href;
        const appIdMatch = url.match(/\/?id=(\d+)/);
        return appIdMatch ? appIdMatch[1] : null;
    }
    const appId = getAppId();
    const pubId = getPubId();
    if (appId) {
        observeAppPage(appId);
    }else if(pubId){
        observePubPage(pubId);
    }else{
        observeUI();
    }
})();
