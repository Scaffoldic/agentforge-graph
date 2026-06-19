package com.example;

// A plain (non-controller) class — must not produce routes even in a Spring app.
public class Helper {
    public String greet() {
        return "hi";
    }
}
