.. raw:: html

   <script>
   function copyCode(button) {
     const codeBlock = button.nextElementSibling;
     if (!codeBlock) return;
     const text = codeBlock.innerText;

     const parts = text.split('$');
     const rightPart = parts.slice(1).join('$');;

     navigator.clipboard.writeText(rightPart).then(() => {
       button.innerText = 'Copied';
       button.disabled = true;
       setTimeout(() => {
         button.innerText = button.getAttribute('data-label');
         button.disabled = false;
       }, 2000);
     }).catch(() => {
       button.innerText = 'Failed';
     });
   }
   </script>

Key Generation
==============

This guide provides detailed instructions for generating SSH key pairs and securely deploying public keys to remote worker machines in various operating system configurations within the Agilab environment.

In the rest of the guide, I would refer to:

- Manager: The local machine from which SSH connections are initiated.
- Worker: The remote machine that accepts SSH connections.
- Remote account: The user account on the worker machine used for SSH login.

1. Generate the keys
~~~~~~~~~~~~~~~~~~~~

.. tabs::

    .. tab:: Global

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           manager$ ssh-keygen -a 100 -t ed25519

You will be prompted for a passphrase. don't enter one (double return).

If you have not changed the default path, the public key will be stored in ``~/.ssh/id_ed25519.pub`` and the private key in ``~/.ssh/id_ed25519``.

2. Loading the private key in SSH Agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

2.1 Load the private key
^^^^^^^^^^^^^^^^^^^^^^^^

.. tabs::

    .. tab:: **Linux**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            manager$ ssh-add ~/.ssh/id_ed25519

    .. tab:: **Windows**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

            manager$ ssh-add $env:USERPROFILE/.ssh/id_ed25519


2.2 Verify the key Addition
^^^^^^^^^^^^^^^^^^^^^^^

.. tabs::

    .. tab:: Global

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            manager$ ssh-add -l

It should display the **public key** (not private). To manually check the public key:

.. tabs::

    .. tab:: **Linux**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           manager$ cat ~/.ssh/id_ed25519.pub

    .. tab:: **Windows**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

           manager$ cat $env:USERPROFILE/.ssh/id_ed25519.pub


If you have set a passphrase, you will be asked to enter it. If you encounter any permission-related errors, refer to the `Permissions`_ section.

On Linux, if a window titled "Enter password to unlock the private key" appears when trying to establish an SSH connection, enter the passphrase and check the box "Automatically unlock this key whenever I'm logged in".

3. Copy the public key to the server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.1 Allow your key
^^^^^^^^^^^^^^^^^^

Follow these steps to add your key to the `authorized_keys` file of each workers:

.. tabs::

    .. tab:: **Manager Unix**

        Worker Linux:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           manager$ ssh-copy-id -i ~/.ssh/id_ed25519 <remote account>@<worker ip>

        Worker Windows:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            manager$ cat ~/.ssh/id_ed25519.pub | ssh <remote account>@<worker ip> powershell -NoProfile -Command "Add-Content -Encoding ascii -Path 'C:\\Users\\<remote account>\\.ssh\\authorized_keys' -Value '([Console]::In.ReadToEnd())'"

    .. tab:: **Manager Windows**

        Worker Unix:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

           manager$ Get-Content -Raw "${env:USERPROFILE}\\.ssh\\id_ed25519.pub" | ssh <remote account>@<worker ip> "cat >> ~/.ssh/authorized_keys"

        Worker Windows:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

           manager$ Get-Content -Raw "${env:USERPROFILE}\\.ssh\\id_ed25519.pub" | ssh <remote account>@<worker ip> powershell -NoProfile -Command "Add-Content -Encoding ascii -Path 'C:\\Users\\<remote account>\\.ssh\\authorized_keys' -Value '([Console]::In.ReadToEnd())'"

3.2 Verification
^^^^^^^^^^^^^^^^

.. tabs::

    .. tab:: Global

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            manager$ ssh <remote account>@<worker ip>


.. admonition:: Success

    It should connect without asking the account password !

Bidirectional trust between worker Macs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When two macOS workers must talk to each other (for example ``<worker_a_ip>`` and ``<worker_b_ip>``),
install the same SSH key pair on both hosts so either side can ``ssh`` without a password prompt.
Assuming the login user is ``<remote account>`` (adjust if yours differs):

1. Enable Remote Login on each Mac if it is not already on::

       sudo systemsetup -setremotelogin on

2. From ``<worker_a_ip>`` push the public key to ``<worker_b_ip>``::

       ssh-copy-id -i ~/.ssh/id_ed25519 <remote account>@<worker_b_ip>

3. From ``<worker_b_ip>`` push the same key back to ``<worker_a_ip>``::

       ssh-copy-id -i ~/.ssh/id_ed25519 <remote account>@<worker_a_ip>

4. Verify both directions once so the host keys land in ``~/.ssh/known_hosts``::

       ssh <remote account>@<worker_b_ip> hostname
       ssh <remote account>@<worker_a_ip> hostname

Each command should print the remote ``hostname`` without asking for a password. If either side still
prompts, re-run ``ssh-copy-id`` and make sure ``~/.ssh/authorized_keys`` on the target contains the
public key content.

Troubleshooting
~~~~~~~~~~~~~~~~~~

SSHD Service
^^^^^^^^^^^^

Check the service status:
-------------------------

.. tabs::

    .. tab:: **Linux**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           sudo systemctl status ssh  # Check SSH Server status
           ssh-add -L  # Check if the SSH agent is running

    .. tab:: **Windows (admin)**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

           Get-Service sshd
           Get-Service ssh-agent

Check the configuration
-----------------------

Check the SSH server configuration in the ``sshd_config`` file:

- **Windows Server**: ``C:\ProgramData\ssh\sshd_config``
- **Unix Server**: ``/etc/ssh/sshd_config``


Ensure the following configuration is set:

.. code-block:: none

    PubkeyAuthentication yes
    PasswordAuthentication no

To modify, open the file in an **elevated text editor**, update the lines as shown above, and restart the SSH server (see `Restart the SSHD service`_ section).

Restart the SSHD service
------------------------

.. tabs::

    .. tab:: **Linux**

        .. raw:: html

          <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           workers$ sudo systemctl restart ssh  # Restart SSH Server
           workers$ eval "$(ssh-agent -s)"  # Restart SSH Agent

    .. tab:: **Windows (admin)**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

           workers$ Restart-Service sshd   # Restart SSH Server
           workers$ Restart-Service ssh-agent   # Restart SSH Agent

Permissions
-----------

.. tabs::

    .. tab:: **Linux**

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            chmod 700 ~/.ssh
            chmod 600 ~/.ssh/id_ed25519

        To verify:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

            ls -l "~/.ssh"

    .. tab:: **Windows**

        Ensure that the ``.ssh`` folder and the ``id_ed25519`` file have the correct permissions:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: bash

           .ssh\id_ed25519        AUTORITE NT\Système:(F)
                      BUILTIN\Administrateurs:(F)
                      %USERNAME%:(M)

        To view permissions:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

            icacls "$env:userprofile\.ssh"

        To set correct permissions:

        .. raw:: html

           <button class="copy-btn-left" data-label="Copy" onclick="copyCode(this)" aria-label="Copy">Copy</button>

        .. code-block:: powershell

            icacls "$env:userprofile\.ssh\id_ed25519" /inheritance:r /grant "AUTORITE NT\Système:(F)" "BUILTIN\Administrateurs:(F)" "$env:username:(M)"

Useful links
~~~~~~~~~~~~

If you need more informations about ssh configuration, the following guides might be helpful:

- For **Unix**: `Debian documentation <https://wiki.debian.org/SSH>`__

- For **Windows**/ `Microsoft documentation <https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration>`__
